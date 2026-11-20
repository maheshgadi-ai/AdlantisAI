"""Channel plans may paraphrase ordinary facts. Everything else keeps its exact wording."""

import pytest

from adlantis.orchestrator.render_html import render_html
from adlantis.orchestrator.render_markdown import render_markdown
from adlantis.rules import RuleContext, check_asset
from adlantis.rules.claim_gate import settle_claims
from adlantis.schemas import (
    ApprovedFact,
    CampaignAsset,
    Citation,
    DraftClaim,
    EvidenceStore,
    FactSheet,
)
from adlantis.schemas.kit import CHANNEL_PLAN_LABEL
from tests.orchestrator.kit_helpers import INPUTS, TODAY, make_kit

EXACT_WORDING = "The approved fact must be used in its exact wording."
RELATIONSHIP = "We work directly with Finca Monte Tamsal every season."
SHEET = FactSheet(
    facts=[
        *INPUTS.facts.facts,
        ApprovedFact(
            id="F-020",
            claim_type="product_fact",
            claim=RELATIONSHIP,
            evidence_note="Purchase contracts on file.",
        ),
    ]
)
CTX = RuleContext(brand=INPUTS.brand, facts=SHEET, today=TODAY)
PARAPHRASE = "our direct relationship with the farm"


def plan(text: str, *references: str) -> CampaignAsset:
    return CampaignAsset(
        asset_id="strategy-channel-email",
        channel="strategy",
        fields={"rationale": text},
        references=list(references),
    )


def claim(
    text: str, reference: str = "F-020", passage: str = RELATIONSHIP, **changes
) -> DraftClaim:
    values = {
        "field": "rationale",
        "quote": text,
        "claim_type": "product_fact",
        "references": [reference] if reference else [],
        "verdict": "supported",
        "supporting_passage": passage,
        "reason": "The fact supports this.",
    }
    return DraftClaim.model_validate({**values, **changes})


def settle(asset: CampaignAsset, item: DraftClaim):
    result = settle_claims([item], asset, CTX, EvidenceStore(), check_asset(asset, CTX))
    return result.claims[0]


def test_channel_plan_may_paraphrase_a_cited_fact() -> None:
    assert settle(plan(PARAPHRASE, "F-020"), claim(PARAPHRASE)).verdict == "supported"


def test_paraphrase_still_needs_a_citation() -> None:
    result = settle(plan(PARAPHRASE, "F-020"), claim(PARAPHRASE, reference=""))
    assert (result.verdict, result.reason) == ("unsupported", "The claim cites no source.")


def test_paraphrase_still_needs_the_checker_to_support_it() -> None:
    item = claim(PARAPHRASE, verdict="unsupported", reason="It says more than the fact.")
    assert settle(plan(PARAPHRASE, "F-020"), item).verdict == "unsupported"


def test_paraphrase_still_needs_a_real_supporting_passage() -> None:
    result = settle(plan(PARAPHRASE, "F-020"), claim(PARAPHRASE, passage="Invented proof."))
    assert result.reason == "The supporting passage does not appear in the cited source."


@pytest.mark.parametrize(
    ("asset_id", "channel"),
    [
        ("strategy-message-1", "strategy"),
        ("strategy-positioning", "strategy"),
        ("strategy-concept", "strategy"),
        ("image-email-1", "image_prompt"),
    ],
)
def test_other_plan_sections_keep_exact_wording(asset_id: str, channel: str) -> None:
    asset = plan(PARAPHRASE, "F-020").model_copy(update={"asset_id": asset_id, "channel": channel})
    assert settle(asset, claim(PARAPHRASE)).reason == EXACT_WORDING


def test_published_assets_keep_exact_wording() -> None:
    asset = CampaignAsset(
        asset_id="email-1",
        channel="email",
        fields={"rationale": PARAPHRASE},
        citations=[Citation(text=PARAPHRASE, references=["F-020"])],
        references=["F-020"],
    )
    assert settle(asset, claim(PARAPHRASE)).reason == EXACT_WORDING


@pytest.mark.parametrize(
    "quote",
    ["the 7-harvest relationship (F-004)", "seven years and 7 harvests with the farm"],
)
def test_numbers_in_a_channel_plan_keep_exact_wording(quote: str) -> None:
    passage = SHEET.get("F-004").claim
    assert settle(plan(quote, "F-004"), claim(quote, "F-004", passage)).reason == EXACT_WORDING


def test_regulated_claim_type_in_a_channel_plan_keeps_exact_wording() -> None:
    quote = "an award for our washed coffee"
    passage = SHEET.get("F-008").claim
    item = claim(quote, "F-008", passage, claim_type="superlative")
    assert settle(plan(quote, "F-008"), item).reason == EXACT_WORDING


def test_regulated_fact_mislabeled_by_the_checker_keeps_exact_wording() -> None:
    quote = "a subscriber who wakes up early for it"
    passage = SHEET.get("F-009").claim
    assert settle(plan(quote, "F-009"), claim(quote, "F-009", passage)).reason == EXACT_WORDING


def test_glossary_term_in_a_channel_plan_keeps_exact_wording() -> None:
    quote = "washed coffee from our direct relationship"
    assert settle(plan(quote, "F-020"), claim(quote)).reason == EXACT_WORDING


def test_rules_engine_still_applies_to_channel_plans() -> None:
    report = check_asset(plan("The best coffee in the world.", "F-020"), CTX)
    assert report.for_rule("superlative_claim")


def test_channel_plans_are_labeled_in_every_format() -> None:
    kit = make_kit()
    assert CHANNEL_PLAN_LABEL == "Internal planning, not for publication."
    assert kit.channel_plan_label == CHANNEL_PLAN_LABEL
    assert CHANNEL_PLAN_LABEL in render_markdown(kit)
    assert CHANNEL_PLAN_LABEL in render_html(kit)
    assert CHANNEL_PLAN_LABEL in kit.model_dump_json()


def test_channel_plan_text_appears_in_every_format() -> None:
    kit = make_kit()
    rationale = kit.strategy.channel_mix[0].rationale
    assert rationale in render_markdown(kit) and rationale in render_html(kit)


def test_label_does_not_change_the_kit_fingerprint() -> None:
    kit = make_kit()
    data = kit.model_dump(mode="json")
    del data["channel_plan_label"]
    older = type(kit).model_validate(data)
    assert older.compute_hash() == kit.content_sha256
