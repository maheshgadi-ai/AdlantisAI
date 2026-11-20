"""Checks assets, sends failures back for targeted fixes, and ships only what passes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, TypeVar

from adlantis.llm.types import LLMError
from adlantis.orchestrator.revision import apply_edits
from adlantis.rules.channels import required_mentions
from adlantis.schemas.brand import BrandKit
from adlantis.schemas.claim_check import ClaimCheckResult
from adlantis.schemas.copy import CampaignAsset, RevisionPlan, RevisionRequest
from adlantis.schemas.facts import FactSheet
from adlantis.schemas.ledger import IssueLedger, IssueReport, IssueVerdict, LedgerIssue
from adlantis.schemas.research import ResearchFinding
from adlantis.schemas.review import AssetGap, ReviewedAsset, ReviewOutcome

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

MAX_REVISION_ROUNDS = 2
_DEFAULT_FIX = "Remove the claim, or support it with an approved fact."


class AssetChecker(Protocol):
    """Anything that can judge an asset."""

    def run(self, data: CampaignAsset) -> ClaimCheckResult: ...


class AssetReviser(Protocol):
    """Anything that can propose edits for an asset."""

    def revise(self, data: RevisionRequest) -> RevisionPlan: ...


@dataclass(frozen=True)
class ReviewContext:
    """The sources available when fixing issues."""

    brand: BrandKit
    facts: FactSheet
    findings: list[ResearchFinding]
    today: date
    allowed_references: frozenset[str]
    product_name: str = ""


def blocking_reports(result: ClaimCheckResult) -> list[IssueReport]:
    """One ledger report per distinct problem that keeps this asset out of the kit."""
    reports: dict[tuple[str, str, str], IssueReport] = {}
    for claim in result.blocked_claims:
        kind = "prohibited_claim" if claim.verdict == "prohibited" else "unsupported_claim"
        report = IssueReport(
            asset_id=result.asset_id,
            kind=kind,
            quote=claim.quote,
            problem=claim.reason,
            fix=claim.fix or _DEFAULT_FIX,
        )
        reports.setdefault(report.key, report)
    for error in result.rule_errors:
        report = IssueReport(
            asset_id=result.asset_id,
            kind="rule_violation",
            quote=error.quote or error.rule,
            problem=error.message,
            fix=error.fix,
        )
        reports.setdefault(report.key, report)
    return list(reports.values())


@dataclass
class _Progress:
    """Where one asset stands in the loop."""

    current: CampaignAsset
    best: CampaignAsset | None = None
    best_result: ClaimCheckResult | None = None
    best_reports: list[IssueReport] = field(default_factory=list)
    revisions: int = 0
    open: bool = True
    failure: str | None = None

    def improves(self, reports: list[IssueReport]) -> bool:
        """True unless this version has more problems than the best one so far."""
        return self.best is None or len(reports) <= len(self.best_reports)

    def keep(self, result: ClaimCheckResult, reports: list[IssueReport]) -> None:
        """Make the current version the best one."""
        self.best, self.best_result, self.best_reports = self.current, result, reports


class ReviewLoop:
    """Runs the check and revise cycle with an issue ledger."""

    def __init__(
        self,
        checker: AssetChecker,
        reviser: AssetReviser,
        context: ReviewContext,
        max_rounds: int = MAX_REVISION_ROUNDS,
        concurrency: int = 1,
    ) -> None:
        self.checker = checker
        self.reviser = reviser
        self.context = context
        self.max_rounds = max_rounds
        self.concurrency = concurrency

    def review(
        self, assets: list[CampaignAsset], ledger: IssueLedger | None = None
    ) -> ReviewOutcome:
        """Check every asset, revise failures up to the round limit, and sort the results.

        Pass `ledger` to record these issues alongside earlier ones from the same run.
        """
        ledger = IssueLedger() if ledger is None else ledger
        progress = [_Progress(current=asset) for asset in assets]
        for round_number in range(1, self.max_rounds + 2):
            pending = [item for item in progress if item.open]
            if not pending:
                break
            self._check_round(pending, ledger, round_number)
            for item in pending:
                if round_number > self.max_rounds:
                    item.open = False
            revising = [item for item in pending if item.open]
            self._map(lambda item: self._revise(item, ledger), revising)
        return _outcome(progress, ledger)

    def _check_round(
        self, pending: list[_Progress], ledger: IssueLedger, round_number: int
    ) -> None:
        reports: list[IssueReport] = []
        verdicts: list[IssueVerdict] = []
        for item, result in zip(pending, self._map(self._check, pending), strict=True):
            if result is None:
                continue
            found = blocking_reports(result)
            reports += found
            if not item.improves(found):
                continue  # a discarded version resolves nothing on the version that was kept
            keys = {report.key for report in found}
            verdicts += [
                IssueVerdict(issue_id=issue.id, status="resolved")
                for issue in ledger.active(item.current.asset_id)
                if issue.key not in keys
            ]
            item.keep(result, found)
            item.open = bool(found)
        ledger.apply(reports, verdicts, round_number)

    def _check(self, item: _Progress) -> ClaimCheckResult | None:
        try:
            return self.checker.run(item.current)
        except LLMError as exc:  # an asset that cannot be verified never ships
            logger.warning("claim check failed", extra={"asset": item.current.asset_id})
            item.open, item.failure = False, f"The claim check could not finish: {exc}"
            return None

    def _map(self, work: Callable[[T], R], items: list[T]) -> list[R]:
        """Run independent work at once, returning results in the order of `items`."""
        if self.concurrency <= 1 or len(items) < 2:
            return [work(item) for item in items]
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            return list(pool.map(work, items))

    def _revise(self, item: _Progress, ledger: IssueLedger) -> None:
        """Propose fixes from the best version, so a bad revision never compounds."""
        asset = item.best
        keys = {report.key for report in item.best_reports}
        issues: list[LedgerIssue] = [i for i in ledger.active(asset.asset_id) if i.key in keys]
        if not issues:
            item.open = False
            return
        mentions = required_mentions(asset.channel, self.context.product_name)
        request = RevisionRequest(
            asset=asset,
            issues=issues,
            brand=self.context.brand,
            facts=self.context.facts,
            findings=self.context.findings,
            today=self.context.today,
            required_mentions=mentions,
        )
        try:
            plan = self.reviser.revise(request)
        except LLMError:
            logger.warning("revision failed", extra={"asset": asset.asset_id})
            item.open = False
            return
        edited = apply_edits(
            asset, plan, {issue.id for issue in issues}, self.context.allowed_references, mentions
        )
        if edited.applied == 0:
            item.open = False
            return
        item.current = edited.asset
        item.revisions += 1


def _outcome(progress: list[_Progress], ledger: IssueLedger) -> ReviewOutcome:
    assets: list[ReviewedAsset] = []
    gaps: list[AssetGap] = []
    for item in progress:
        asset_id = item.current.asset_id
        if item.best_result is not None and item.best_result.passed:
            assets.append(
                ReviewedAsset(
                    asset=item.best,
                    claims=item.best_result.claims,
                    warnings=item.best_result.warnings,
                    revisions=item.revisions,
                )
            )
            continue
        reason = item.failure or "Issues remained after the maximum number of revisions."
        gaps.append(
            AssetGap(
                asset_id=asset_id,
                channel=item.current.channel,
                reason=reason,
                issue_ids=[
                    issue.id
                    for issue in ledger.active(asset_id)
                    if issue.key in {report.key for report in item.best_reports}
                ],
            )
        )
    return ReviewOutcome(assets=assets, gaps=gaps, ledger=ledger)
