"""Sorts rejected claims by seriousness. The checker reads meaning, and code has the last word."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from typing import Literal

from pydantic import BaseModel

from adlantis.rules.checks import DETECTORS
from adlantis.rules.text import REFERENCE_ID, find_hits, is_inside, normalize, wording_spans
from adlantis.schemas.claims import CLAIM_TAXONOMY, ClaimVerdict
from adlantis.schemas.inputs import CampaignInputs
from adlantis.schemas.triage import TriageItem

ClaimSeverity = Literal[
    "fabricated_or_regulated", "paraphrased_fact", "uncited_true", "call_to_action"
]
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


class BadClaim(BaseModel):
    """A claim the checker rejected, and whether the copy cited anything for it."""

    quote: str
    verdict: ClaimVerdict
    cited: bool


class ClassifiedClaim(BaseModel):
    """A rejected claim, how serious it is, and why."""

    quote: str
    verdict: ClaimVerdict
    category: ClaimSeverity
    cited: bool
    source: str = ""
    reason: str = ""


def _numbers(text: str, inputs: CampaignInputs) -> set[str]:
    """Numbers a statement asserts. Digits in names such as "Arc 7" and fact IDs are not claims."""
    clean = REFERENCE_ID.sub(" ", normalize(text))
    names = [inputs.brand.name, *inputs.brand.aliases, *inputs.product.names]
    for name in sorted(names, key=len, reverse=True):
        clean = re.sub(re.escape(normalize(name)), " ", clean, flags=re.IGNORECASE)
    return set(_NUMBER.findall(clean))


def makes_a_regulated_claim(quote: str, inputs: CampaignInputs, today: date) -> bool:
    """True when the wording makes a regulated claim that no unexpired fact approves."""
    text = normalize(quote)
    for claim_type, patterns in DETECTORS.items():
        if not CLAIM_TAXONOMY[claim_type].regulated:
            continue
        wordings = [
            wording
            for fact in inputs.facts.facts
            if fact.claim_type == claim_type and not fact.is_expired(today)
            for wording in fact.wordings
        ]
        approved = wording_spans(wordings, text)
        if any(not is_inside(hit, approved) for hit in find_hits(patterns, text)):
            return True
    return False


def _approved_text(inputs: CampaignInputs, today: date) -> dict[str, str]:
    texts = {
        fact.id: " ".join([*fact.wordings, fact.paraphrase_scope or ""])
        for fact in inputs.facts.facts
        if not fact.is_expired(today)
    }
    texts.update({entry.term: entry.wording for entry in inputs.brand.glossary})
    return texts


def _settle(
    claim: BadClaim, item: TriageItem | None, inputs: CampaignInputs, today: date
) -> tuple[ClaimSeverity, str, str]:
    numbers = _numbers(claim.quote, inputs)
    if claim.verdict == "prohibited":
        return "fabricated_or_regulated", "", "The rules or the brand prohibit this claim."
    if makes_a_regulated_claim(claim.quote, inputs, today):
        return "fabricated_or_regulated", "", "Regulated wording without an approved fact."
    if item is None:
        return "fabricated_or_regulated", "", "The checker did not classify this claim."
    if item.category == "call_to_action":
        if numbers:
            return "fabricated_or_regulated", "", "A call to action that states a number."
        return "call_to_action", "", item.reason
    if item.category != "supported_by_fact":
        return "fabricated_or_regulated", "", item.reason
    approved = _approved_text(inputs, today)
    sources = [ref for ref in item.fact_ids if ref in approved]
    if not sources or len(sources) != len(item.fact_ids):
        return "fabricated_or_regulated", "", "It names no unexpired approved fact."
    if not numbers <= set().union(*(_numbers(approved[ref], inputs) for ref in sources)):
        return "fabricated_or_regulated", ", ".join(sources), "It states a number no fact gives."
    category: ClaimSeverity = "paraphrased_fact" if claim.cited else "uncited_true"
    return category, ", ".join(sources), item.reason


def settle_triage(
    claims: Sequence[BadClaim], items: Sequence[TriageItem], inputs: CampaignInputs, today: date
) -> list[ClassifiedClaim]:
    """Turn the checker's readings into categories. Code can only make them more serious."""
    by_index = {item.index: item for item in items}
    settled = []
    for number, claim in enumerate(claims, 1):
        category, source, reason = _settle(claim, by_index.get(number), inputs, today)
        settled.append(
            ClassifiedClaim(
                quote=claim.quote,
                verdict=claim.verdict,
                category=category,
                cited=claim.cited,
                source=source,
                reason=reason,
            )
        )
    return settled
