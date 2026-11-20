"""Code that has the last word on every claim verdict.

The checker model proposes verdicts. Code can only make them stricter: a "supported" verdict
stands only if the proof is real, and a rule violation always overrides the model.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from adlantis.rules.context import RuleContext
from adlantis.rules.text import REFERENCE_ID, contains_text, names_only, normalize
from adlantis.schemas.assets import AssetCopy
from adlantis.schemas.brand import GlossaryEntry
from adlantis.schemas.channels import SECTION_CHANNELS, is_channel_plan
from adlantis.schemas.claim_check import CheckedClaim, ClaimCheckResult, DraftClaim
from adlantis.schemas.claims import CLAIM_TAXONOMY, ClaimVerdict
from adlantis.schemas.copy import CampaignAsset
from adlantis.schemas.evidence_store import EvidenceStore
from adlantis.schemas.facts import ApprovedFact
from adlantis.schemas.rules import RuleId, RuleReport, RuleViolation

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


class _Decision(NamedTuple):
    verdict: ClaimVerdict
    reason: str
    decided_by: str
    rule: RuleId | None = None
    passage: str | None = None


def _span(text: str, quote: str) -> tuple[int, int] | None:
    words = normalize(quote).split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(word) for word in words)
    match = re.search(pattern, normalize(text), re.IGNORECASE)
    return match.span() if match else None


def _overlapping_error(
    draft: DraftClaim, asset: AssetCopy, errors: list[RuleViolation]
) -> RuleViolation | None:
    span = _span(asset.fields.get(draft.field, ""), draft.quote)
    if span is None:
        return None
    for error in errors:
        located = error.field == draft.field and error.start is not None and error.end is not None
        if located and error.start < span[1] and span[0] < error.end:
            return error
    return None


def _approved_definition(statement: str, field_text: str, ctx: RuleContext) -> GlossaryEntry | None:
    """The glossary entry covering this statement, when the field uses it word for word."""
    for entry in ctx.brand.glossary:
        if contains_text(field_text, entry.wording) and contains_text(entry.wording, statement):
            return entry
    return None


def _same_statement(first: str, second: str) -> bool:
    return contains_text(first, second) or contains_text(second, first)


def _copy_citations(draft: DraftClaim, asset: CampaignAsset) -> set[str]:
    """The sources the copy itself attached to this statement."""
    if asset.channel in SECTION_CHANNELS:  # a plan section cites its sources as a whole
        return set(asset.references)
    return {
        reference
        for citation in asset.citations
        if _same_statement(citation.text, draft.quote)
        for reference in citation.references
    }


def _claimed_numbers(quote: str, ctx: RuleContext, evidence: EvidenceStore) -> set[str]:
    """The numbers a claim states. A citation such as "(F-004)" is not a number in the claim."""

    def without_citation(match: re.Match[str]) -> str:
        known = ctx.facts.get(match.group()) or evidence.get(match.group())
        return " " if known else match.group()

    return set(_NUMBER.findall(REFERENCE_ID.sub(without_citation, normalize(quote))))


def _may_paraphrase(
    draft: DraftClaim,
    asset: CampaignAsset,
    facts: list[ApprovedFact],
    ctx: RuleContext,
    evidence: EvidenceStore,
) -> bool:
    """Internal channel plans may reword a fact, except numbers, regulated claims, and terms."""
    if not is_channel_plan(asset.asset_id):
        return False
    types = {draft.claim_type, *(fact.claim_type for fact in facts)}
    regulated = any(CLAIM_TAXONOMY[claim_type].regulated for claim_type in types)
    defines_a_term = any(contains_text(draft.quote, e.term) for e in ctx.brand.glossary)
    return not (regulated or defines_a_term or _claimed_numbers(draft.quote, ctx, evidence))


def _support_problem(
    draft: DraftClaim, asset: CampaignAsset, ctx: RuleContext, evidence: EvidenceStore
) -> str | None:
    """Why a "supported" verdict cannot stand, or None when the proof holds."""
    if not draft.references:
        return "The claim cites no source."
    if not set(draft.references) <= _copy_citations(draft, asset):
        return "The copy does not cite that source for this statement."
    passages: list[str] = []
    facts = []
    for reference in draft.references:
        fact = ctx.facts.get(reference)
        record = evidence.get(reference)
        if fact is not None:
            if fact.is_expired(ctx.today):
                return f"{reference} has expired."
            facts.append(fact)
            passages.extend(fact.wordings)
        elif record is not None and record.status == "usable":
            passages.append(record.excerpt)
        else:
            return f"{reference} is not a usable source."
    if CLAIM_TAXONOMY[draft.claim_type].regulated and not any(
        fact.claim_type == draft.claim_type for fact in facts
    ):
        return f"A {draft.claim_type} claim needs an approved fact of that type."
    if not any(contains_text(passage, draft.supporting_passage) for passage in passages):
        return "The supporting passage does not appear in the cited source."
    numbers = set(_NUMBER.findall(" ".join(normalize(passage) for passage in passages)))
    if not _claimed_numbers(draft.quote, ctx, evidence) <= numbers:
        return "The claim states a number the cited source does not contain."
    exact = [fact for fact in facts if fact.wording == "exact"]
    wording_applies = len(exact) == len(passages) and not _may_paraphrase(
        draft, asset, facts, ctx, evidence
    )
    if wording_applies and not any(
        _same_statement(wording, draft.quote) for fact in exact for wording in fact.wordings
    ):
        return "The approved fact must be used in its exact wording."
    return None


def _judge(
    draft: DraftClaim,
    asset: CampaignAsset,
    ctx: RuleContext,
    evidence: EvidenceStore,
    errors: list[RuleViolation],
) -> _Decision:
    if not contains_text(asset.fields.get(draft.field, ""), draft.quote):
        return _Decision("unsupported", "The quoted claim does not appear in the copy.", "code")
    if draft.claim_type in ctx.brand.banned_claim_types:
        return _Decision("prohibited", f"The brand bans {draft.claim_type} claims.", "code")
    error = _overlapping_error(draft, asset, errors)
    if error is not None:
        return _Decision("prohibited", error.message, "code", error.rule)
    if draft.verdict != "supported":
        return _Decision(draft.verdict, draft.reason, "model")
    entry = _approved_definition(draft.quote, asset.fields.get(draft.field, ""), ctx)
    if entry is not None:
        return _Decision("supported", draft.reason, "model", passage=entry.wording)
    problem = _support_problem(draft, asset, ctx, evidence)
    if problem:
        return _Decision("unsupported", problem, "code")
    return _Decision("supported", draft.reason, "model")


def _unassessed(
    asset: CampaignAsset, drafts: list[DraftClaim], ctx: RuleContext, start: int
) -> list[CheckedClaim]:
    """Statements the copy cited but the checker never ruled on fail closed."""
    missing: list[CheckedClaim] = []
    for citation in asset.citations:
        if names_only(citation.text, ctx.identifiers):
            continue
        if any(_same_statement(citation.text, draft.quote) for draft in drafts):
            continue
        field = next((n for n, t in asset.fields.items() if contains_text(t, citation.text)), "")
        if _approved_definition(citation.text, asset.fields.get(field, ""), ctx):
            continue
        missing.append(
            CheckedClaim(
                id=f"{asset.asset_id}/C{start + len(missing)}",
                asset_id=asset.asset_id,
                field=field,
                quote=citation.text,
                claim_type="other",
                references=citation.references,
                verdict="unsupported",
                reason="The claim checker did not assess this cited statement.",
                decided_by="code",
            )
        )
    return missing


def settle_claims(
    drafts: list[DraftClaim],
    asset: CampaignAsset,
    ctx: RuleContext,
    evidence: EvidenceStore,
    report: RuleReport,
) -> ClaimCheckResult:
    """Turn the checker's proposals and the rule report into final verdicts."""
    errors = report.errors
    claims: list[CheckedClaim] = []
    absorbed: list[RuleViolation] = []
    drafts = [draft for draft in drafts if not names_only(draft.quote, ctx.identifiers)]
    for number, draft in enumerate(drafts, 1):
        decision = _judge(draft, asset, ctx, evidence, errors)
        absorbed += [e for e in errors if e is _overlapping_error(draft, asset, [e])]
        claims.append(
            CheckedClaim(
                id=f"{asset.asset_id}/C{number}",
                asset_id=asset.asset_id,
                field=draft.field,
                quote=draft.quote,
                claim_type=draft.claim_type,
                references=draft.references,
                verdict=decision.verdict,
                supporting_passage=decision.passage or draft.supporting_passage,
                reason=decision.reason,
                fix=draft.fix,
                decided_by=decision.decided_by,
                rule=decision.rule,
            )
        )
    claims += _unassessed(asset, drafts, ctx, len(claims) + 1)
    return ClaimCheckResult(
        asset_id=asset.asset_id,
        claims=claims,
        rule_errors=[e for e in errors if not any(e is seen for seen in absorbed)],
        warnings=report.warnings,
    )
