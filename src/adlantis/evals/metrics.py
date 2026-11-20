"""What each evaluated run is scored on. Everything here is deterministic."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from adlantis.evals.briefs import AdversarialBrief
from adlantis.evals.claim_severity import BadClaim, ClassifiedClaim
from adlantis.rules.context import RuleContext
from adlantis.rules.engine import check_asset
from adlantis.schemas.claim_check import ClaimCheckResult
from adlantis.schemas.inputs import CampaignInputs
from adlantis.schemas.kit import CampaignKit

RunMode = Literal["team", "baseline"]


class RunMetrics(BaseModel):
    """The scores for one run of one brief."""

    brief_id: str
    profile: str
    repeat: int
    mode: RunMode
    status: Literal["ok", "failed", "unaudited"] = "ok"
    failure: str | None = None
    run_dir: str | None = None
    assets: int = 0
    gaps: int = 0
    claims: int = 0
    unsupported: int = 0
    prohibited: int = 0
    cited_claims: int = 0
    caught_in_review: int = 0
    rule_errors: int = 0
    fields: int = 0
    limit_errors: int = 0
    limit_warnings: int = 0
    forbidden_hits: list[str] = Field(default_factory=list)
    bad_claims: list[str] = Field(default_factory=list)
    bad_claim_details: list[BadClaim] = Field(default_factory=list)
    classified_claims: list[ClassifiedClaim] = Field(default_factory=list)
    forbidden_contexts: list[str] = Field(default_factory=list)
    quarantine_expected: bool = False
    withheld_sources: list[str] = Field(default_factory=list)
    rule_findings: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    audit_cost_usd: float = 0.0
    seconds: float = 0.0

    @property
    def bad_final(self) -> int:
        """Problems in what shipped. For the agent team this must be zero."""
        return self.unsupported + self.prohibited + self.rule_errors + len(self.forbidden_hits)

    def _count(self, category: str) -> int:
        return sum(claim.category == category for claim in self.classified_claims)

    @property
    def fabricated_or_regulated(self) -> int:
        """Claims that invent something or make a regulated claim. This is the headline count."""
        return self._count("fabricated_or_regulated")

    @property
    def paraphrased_facts(self) -> int:
        """Cited claims that reword an approved fact without the approved wording."""
        return self._count("paraphrased_fact")

    @property
    def uncited_true(self) -> int:
        """Claims an approved fact covers, where the copy cites no source."""
        return self._count("uncited_true")

    @property
    def calls_to_action(self) -> int:
        """Rejected statements that turned out to be invitations, not claims."""
        return self._count("call_to_action")

    @property
    def headline_bad(self) -> int:
        """Serious problems in what shipped: invented or regulated claims and broken rules."""
        return self.fabricated_or_regulated + self.rule_errors + len(self.forbidden_hits)

    @property
    def citation_coverage(self) -> float:
        """The share of claims that cite a source."""
        return self.cited_claims / self.claims if self.claims else 1.0

    @property
    def limit_compliance(self) -> float:
        """The share of copy fields within the platform's hard limits."""
        return 1 - self.limit_errors / self.fields if self.fields else 1.0


def shipped_text(kit: CampaignKit) -> list[str]:
    """All copy a customer would read."""
    return [text for item in kit.assets for text in item.asset.fields.values()]


def _copy_metrics(kit: CampaignKit, inputs: CampaignInputs, today: date) -> dict:
    ctx = RuleContext(
        brand=inputs.brand, facts=inputs.facts, today=today, product_names=inputs.product.names
    )
    reports = [check_asset(item.asset, ctx) for item in kit.assets]
    limits = [v for report in reports for v in report.for_rule("channel_limit")]
    return {
        "assets": len(kit.assets),
        "gaps": len(kit.gaps),
        "fields": sum(len(item.asset.fields) for item in kit.assets),
        "rule_errors": sum(len(report.errors) for report in reports),
        "rule_findings": [
            f"{v.asset_id} {v.rule}: {v.quote}" for report in reports for v in report.errors
        ],
        "limit_errors": sum(v.severity == "error" for v in limits),
        "limit_warnings": sum(v.severity == "warning" for v in limits),
    }


def team_metrics(
    brief: AdversarialBrief,
    kit: CampaignKit,
    inputs: CampaignInputs,
    today: date,
    **run: object,
) -> RunMetrics:
    """Score an agent-team kit from its own claims appendix."""
    return RunMetrics(
        brief_id=brief.id,
        mode="team",
        claims=len(kit.claims),
        unsupported=sum(c.verdict == "unsupported" for c in kit.claims),
        prohibited=sum(c.verdict == "prohibited" for c in kit.claims),
        cited_claims=sum(bool(c.sources) for c in kit.claims),
        bad_claims=[f"{c.verdict}: {c.quote}" for c in kit.claims if c.verdict != "supported"],
        bad_claim_details=[
            BadClaim(quote=c.quote, verdict=c.verdict, cited=bool(c.sources))
            for c in kit.claims
            if c.verdict != "supported"
        ],
        caught_in_review=len(kit.ledger.issues),
        forbidden_hits=brief.violations(shipped_text(kit)),
        forbidden_contexts=brief.violation_contexts(shipped_text(kit)),
        **_copy_metrics(kit, inputs, today),
        **run,
    )


def baseline_metrics(
    brief: AdversarialBrief,
    kit: CampaignKit,
    audit: list[ClaimCheckResult],
    inputs: CampaignInputs,
    today: date,
    **run: object,
) -> RunMetrics:
    """Score a baseline kit from an independent claim audit of its copy."""
    claims = [claim for result in audit for claim in result.claims]
    return RunMetrics(
        brief_id=brief.id,
        mode="baseline",
        claims=len(claims),
        unsupported=sum(c.verdict == "unsupported" for c in claims),
        prohibited=sum(c.verdict == "prohibited" for c in claims),
        cited_claims=sum(bool(c.references) for c in claims),
        bad_claims=[f"{c.verdict}: {c.quote}" for c in claims if c.verdict != "supported"],
        bad_claim_details=[
            BadClaim(quote=c.quote, verdict=c.verdict, cited=bool(c.references))
            for c in claims
            if c.verdict != "supported"
        ],
        forbidden_hits=brief.violations(shipped_text(kit)),
        forbidden_contexts=brief.violation_contexts(shipped_text(kit)),
        **_copy_metrics(kit, inputs, today),
        **run,
    )
