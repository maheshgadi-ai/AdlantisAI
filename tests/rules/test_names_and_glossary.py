"""Names are not claims, and glossary definitions pass only in their approved wording."""

import pytest
from pydantic import ValidationError

from adlantis.rules import check_asset
from adlantis.rules.claim_gate import settle_claims
from adlantis.rules.text import names_only
from adlantis.schemas import DraftClaim, GlossaryEntry
from tests.agents.copy_helpers import asset, evidence
from tests.rules.helpers import brand, context

NAMES = ("Sample Roasters", "Hollow Reserve", "Hollow Reserve Coffee")
ENTRY = {"term": "Washed coffee", "definition": "the fruit is removed before the bean dries."}
WORDING = "Washed coffee: the fruit is removed before the bean dries."


def draft(quote: str, **changes: object) -> DraftClaim:
    values = {
        "field": "body",
        "quote": quote,
        "claim_type": "product_fact",
        "references": [],
        "verdict": "supported",
        "supporting_passage": quote,
        "reason": "Reads as approved.",
    }
    return DraftClaim.model_validate({**values, **changes})


def named_context():
    return context(product_names=("Hollow Reserve", "Hollow Reserve Coffee"))


def glossary_context():
    return context(brand=brand(glossary=[ENTRY]))


def settle(copy, *drafts: DraftClaim, ctx=None):
    ctx = ctx or named_context()
    return settle_claims(list(drafts), copy, ctx, evidence(), check_asset(copy, ctx))


@pytest.mark.parametrize(
    "text",
    [
        "Hollow Reserve",
        "hollow reserve coffee",
        "Meet Hollow Reserve.",
        "Try Hollow Reserve!",
        "Order Hollow Reserve",
        "Sample Roasters: Hollow Reserve",
    ],
)
def test_names_and_invitations_are_not_claims(text: str) -> None:
    assert names_only(text, NAMES)


@pytest.mark.parametrize(
    "text",
    [
        "Hollow Reserve is the best",
        "Hollow Reserve #1",
        "Hollow Reserve 2026",
        "Award-winning Hollow Reserve",
        "Meet the harvest",
        "Order today",
        "",
    ],
)
def test_anything_more_than_a_name_can_be_a_claim(text: str) -> None:
    assert not names_only(text, NAMES)


def test_part_of_a_longer_word_is_not_a_name() -> None:
    assert not names_only("Hollow Reserved", NAMES)


def test_blank_names_are_ignored() -> None:
    assert not names_only("Meet!", ("", " "))


def test_name_joined_to_an_invitation_word_is_not_a_name() -> None:
    assert not names_only("Hollow Reservethe", NAMES)


def test_context_lists_brand_aliases_and_product_names() -> None:
    ctx = context(brand=brand(aliases=["Sample"]), product_names=("Arc 7",))
    assert ctx.identifiers == ("Sample Roasters", "Sample", "Arc 7")


def test_cited_product_name_needs_no_verdict() -> None:
    copy = asset("Meet Hollow Reserve.", (("Meet Hollow Reserve", ("F-001",)),))
    result = settle(copy)
    assert (result.claims, result.passed) == ([], True)


def test_model_verdict_on_a_bare_name_is_dropped() -> None:
    copy = asset("Hollow Reserve", ())
    result = settle(copy, draft("Hollow Reserve", verdict="unsupported"))
    assert (result.claims, result.passed) == ([], True)


def test_cited_claim_that_includes_a_name_still_needs_a_verdict() -> None:
    text = "Hollow Reserve is roasted weekly."
    result = settle(asset(text, ((text, ("F-001",)),)))
    assert [claim.verdict for claim in result.claims] == ["unsupported"]


def test_ruling_on_the_name_does_not_cover_the_longer_statement() -> None:
    text = "Hollow Reserve is roasted weekly."
    result = settle(asset(text, ((text, ("F-001",)),)), draft("Hollow Reserve"))
    assert [(c.quote, c.verdict) for c in result.claims] == [(text, "unsupported")]


def test_banned_word_next_to_a_name_still_blocks() -> None:
    ctx = context(product_names=("Miracle Reserve",))
    copy = asset("Miracle Reserve", ())
    assert not settle(copy, draft("Miracle Reserve"), ctx=ctx).passed


def test_exact_definition_passes_without_a_citation() -> None:
    claim = settle(asset(WORDING, ()), draft(WORDING), ctx=glossary_context()).claims[0]
    assert (claim.verdict, claim.supporting_passage) == ("supported", WORDING)


def test_definition_is_recorded_as_the_proof() -> None:
    item = draft(WORDING, supporting_passage="Something else.")
    claim = settle(asset(WORDING, ()), item, ctx=glossary_context()).claims[0]
    assert claim.supporting_passage == WORDING


def test_other_claims_beside_a_definition_still_need_proof() -> None:
    text = f"{WORDING} Rests for a week."
    claim = settle(asset(text, ()), draft("Rests for a week."), ctx=glossary_context()).claims[0]
    assert claim.verdict == "unsupported"


def test_quoting_part_of_an_exact_definition_passes() -> None:
    claim = settle(asset(WORDING, ()), draft("the fruit is removed"), ctx=glossary_context())
    assert claim.passed


@pytest.mark.parametrize(
    "text",
    [
        "Washed coffee: the fruit comes off before the bean dries.",
        "Washed coffee means the fruit is removed before the bean dries.",
        "the fruit is removed before the bean dries.",
    ],
)
def test_reworded_definition_is_unsupported(text: str) -> None:
    claim = settle(asset(text, ()), draft(text), ctx=glossary_context()).claims[0]
    assert (claim.verdict, claim.decided_by) == ("unsupported", "code")


def test_claim_added_to_a_definition_is_unsupported() -> None:
    text = f"{WORDING[:-1]} and rests for a week."
    assert settle(asset(text, ()), draft(text), ctx=glossary_context()).claims[0].verdict == (
        "unsupported"
    )


def test_definition_in_another_field_does_not_count() -> None:
    claim = draft(WORDING, field="subject")
    assert settle(asset(WORDING, ()), claim, ctx=glossary_context()).claims[0].verdict == (
        "unsupported"
    )


def test_code_never_upgrades_a_model_rejection_of_a_definition() -> None:
    item = draft(WORDING, verdict="unsupported")
    assert settle(asset(WORDING, ()), item, ctx=glossary_context()).claims[0].verdict == (
        "unsupported"
    )


def test_banned_claim_type_overrides_a_definition() -> None:
    ctx = context(brand=brand(glossary=[ENTRY], banned_claim_types=["health"]))
    claim = settle(asset(WORDING, ()), draft(WORDING, claim_type="health"), ctx=ctx).claims[0]
    assert claim.verdict == "prohibited"


def test_cited_definition_needs_no_separate_verdict() -> None:
    result = settle(asset(WORDING, ((WORDING, ("F-001",)),)), ctx=glossary_context())
    assert (result.claims, result.passed) == ([], True)


def test_glossary_entry_has_one_approved_form() -> None:
    assert GlossaryEntry(**ENTRY).wording == WORDING


def test_repeated_glossary_terms_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must not repeat"):
        brand(glossary=[ENTRY, {**ENTRY, "term": "WASHED COFFEE"}])
