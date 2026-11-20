"""Code checks that decide which proposed research findings are kept."""

from __future__ import annotations

import re

from adlantis.schemas.evidence_store import EvidenceRecord, EvidenceStore
from adlantis.schemas.research import (
    DraftFinding,
    RejectedFinding,
    ResearchDraft,
    ResearchFinding,
)
from adlantis.tools.untrusted import injection_signals, quote_appears_in, sanitize

MIN_QUOTE_CHARS = 12
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _rejection(finding: DraftFinding, store: EvidenceStore) -> str | None:
    cited: list[EvidenceRecord] = []
    for evidence_id in finding.evidence_ids:
        record = store.get(evidence_id)
        if record is None:
            return f"cites unknown evidence {evidence_id[:40]}"
        if record.status != "usable":
            return f"cites quarantined evidence {evidence_id}"
        cited.append(record)
    if injection_signals(f"{finding.statement}\n{finding.supporting_quote}"):
        return "contains instruction-like text"
    if len(sanitize(finding.supporting_quote).strip()) < MIN_QUOTE_CHARS:
        return "supporting quote is too short"
    if not any(quote_appears_in(finding.supporting_quote, record.excerpt) for record in cited):
        return "supporting quote does not appear in the cited evidence"
    sources = " ".join(record.excerpt for record in cited)
    invented = set(_NUMBER.findall(finding.statement)) - set(_NUMBER.findall(sources))
    if invented:
        return f"states numbers not in the cited evidence: {sorted(invented)}"
    return None


def accept_findings(
    draft: ResearchDraft, store: EvidenceStore
) -> tuple[list[ResearchFinding], list[RejectedFinding]]:
    """Keep findings that are grounded in usable evidence and record why others were refused."""
    accepted: list[ResearchFinding] = []
    rejected: list[RejectedFinding] = []
    for finding in draft.findings:
        reason = _rejection(finding, store)
        if reason:
            rejected.append(RejectedFinding(statement=finding.statement, reason=reason))
            continue
        quality = {i: store.get(i).rating.tag() for i in finding.evidence_ids}
        accepted.append(
            ResearchFinding(
                **finding.model_dump(), id=f"R-{len(accepted) + 1}", source_quality=quality
            )
        )
    return accepted, rejected
