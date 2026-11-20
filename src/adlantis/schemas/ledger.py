"""Issue ledger: claim problems tracked across revision rounds with stable IDs.

Without a ledger, each check is a fresh review, so a revision can fix one claim while
reintroducing another. The ledger makes the reviser loop converge:
- issues keep an ID (`I1`, `I2`, ...) and a status (open / resolved / regressed);
- an issue is resolved only by an explicit verdict, never by silence;
- a resolved problem that is reported again becomes regressed instead of a new issue;
- every open or regressed issue blocks its asset from shipping.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

IssueStatus = Literal["open", "resolved", "regressed"]
IssueKind = Literal["unsupported_claim", "prohibited_claim", "rule_violation"]


class IssueReport(BaseModel):
    """One concrete problem in one asset, and how to fix it."""

    asset_id: str
    kind: IssueKind
    quote: str = Field(description="Short exact excerpt from the asset the issue refers to.")
    problem: str
    fix: str = Field(description="A specific, targeted edit the copywriter can act on.")

    @property
    def key(self) -> tuple[str, str, str]:
        """Identity of the problem, ignoring case and spacing in the quote."""
        return self.asset_id, self.kind, " ".join(self.quote.lower().split())


class IssueVerdict(BaseModel):
    """A ruling on an issue already in the ledger."""

    issue_id: str = Field(description="Ledger ID, e.g. 'I3'.")
    status: IssueStatus
    note: str = Field(default="", description="One short sentence of justification.")


class LedgerIssue(IssueReport):
    """An issue with an identity and a lifecycle."""

    id: str
    status: IssueStatus = "open"
    round_raised: int = Field(ge=1)
    round_resolved: int | None = None
    history: list[str] = Field(default_factory=list)

    @property
    def blocking(self) -> bool:
        """Open and regressed issues keep the asset out of the kit."""
        return self.status in ("open", "regressed")


class RoundSummary(BaseModel):
    """What a round changed in the ledger."""

    round: int
    added: list[str] = Field(default_factory=list)
    resolved: list[str] = Field(default_factory=list)
    regressed: list[str] = Field(default_factory=list)
    still_open: list[str] = Field(default_factory=list)
    unverified: list[str] = Field(default_factory=list)


class IssueLedger(BaseModel):
    """All issues raised during a run, with their current status."""

    issues: list[LedgerIssue] = Field(default_factory=list)
    rounds: list[RoundSummary] = Field(default_factory=list)

    def get(self, issue_id: str) -> LedgerIssue | None:
        """The issue with this ID, if any."""
        return next((i for i in self.issues if i.id == issue_id), None)

    def active(self, asset_id: str | None = None) -> list[LedgerIssue]:
        """Open or regressed issues, optionally for one asset."""
        return [i for i in self.issues if i.blocking and asset_id in (None, i.asset_id)]

    def resolved(self) -> list[LedgerIssue]:
        """Issues marked fixed."""
        return [i for i in self.issues if i.status == "resolved"]

    def apply(
        self, reports: list[IssueReport], verdicts: list[IssueVerdict], round_number: int
    ) -> RoundSummary:
        """Record one round: verdicts on known issues first, then the problems reported."""
        summary = RoundSummary(round=round_number)
        ruled = {v.issue_id for v in verdicts}
        for verdict in verdicts:
            self._rule(verdict, round_number, summary)
        for report in reports:
            self._report(report, round_number, summary, ruled)
        summary.unverified = [
            i.id for i in self.active() if i.id not in ruled and i.round_raised < round_number
        ]
        self.rounds.append(summary)
        logger.info("ledger round", extra=summary.model_dump())
        return summary

    def _rule(self, verdict: IssueVerdict, round_number: int, summary: RoundSummary) -> None:
        issue = self.get(verdict.issue_id)
        if issue is None:
            return
        if verdict.status == "resolved" and issue.blocking:
            issue.status, issue.round_resolved = "resolved", round_number
            summary.resolved.append(issue.id)
        elif verdict.status == "regressed" and issue.status == "resolved":
            self._regress(issue, summary)
        elif verdict.status == "open" and issue.blocking:
            summary.still_open.append(issue.id)
        else:
            return  # an invalid transition changes nothing
        note = f" - {verdict.note}" if verdict.note else ""
        issue.history.append(f"r{round_number}: {verdict.status}{note}")

    def _report(
        self, report: IssueReport, round_number: int, summary: RoundSummary, ruled: set[str]
    ) -> None:
        known = next((i for i in self.issues if i.key == report.key), None)
        if known is None:
            issue = LedgerIssue(
                **report.model_dump(),
                id=f"I{len(self.issues) + 1}",
                round_raised=round_number,
                history=[f"r{round_number}: raised"],
            )
            self.issues.append(issue)
            summary.added.append(issue.id)
        elif known.status == "resolved":
            self._regress(known, summary)
            known.history.append(f"r{round_number}: regressed - reported again")
        elif known.id not in ruled:
            ruled.add(known.id)
            summary.still_open.append(known.id)
            known.history.append(f"r{round_number}: open - reported again")

    @staticmethod
    def _regress(issue: LedgerIssue, summary: RoundSummary) -> None:
        issue.status, issue.round_resolved = "regressed", None
        summary.regressed.append(issue.id)
