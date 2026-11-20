"""The two fictional example brands load, agree with each other, and work with the rules."""

from datetime import date
from pathlib import Path

import pytest

from adlantis.orchestrator.kit_store import load_kit
from adlantis.orchestrator.section_review import unverified_statements
from adlantis.rules import RuleContext, check_asset
from adlantis.schemas import AssetCopy, CampaignInputs, load_campaign_inputs

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
BRANDS = ["tamsin-hollow-roasters", "kestrune-cycles"]
TODAY = date(2026, 11, 18)

CLEAN = {
    "tamsin-hollow-roasters": AssetCopy(
        asset_id="clean",
        channel="email",
        fields={
            "subject": "The 2026 Hollow Reserve harvest is here",
            "body": (
                "Hollow Reserve is a washed Caturra from Finca Monte Tamsal in Huila, Colombia. "
                "Expect red apple, panela, and cocoa. Roasted within 48 hours of shipping. "
                "$19 per 12 oz bag. Free shipping on orders over $40 in the contiguous US."
            ),
        },
        references=["F-001", "F-002", "F-003", "F-005", "F-006"],
    ),
    "kestrune-cycles": AssetCopy(
        asset_id="clean",
        channel="email",
        fields={
            "subject": "Book a test ride on the Arc 7",
            "body": (
                "Up to 62 miles per charge in Eco mode. A 500 W rear hub motor and a removable "
                "720 Wh battery. Best Commuter E-Bike, 2026 Dunmarrow Cycling Review Awards. "
                "Arc 7, $2,199. 30-day money-back guarantee on every Arc 7, less return freight."
            ),
        },
        references=["F-001", "F-002", "F-005", "F-006", "F-008"],
    ),
}
DIRTY = {
    "tamsin-hollow-roasters": (
        "A miracle roast that reduces anxiety. Sustainable and the best in town. Only $9. "
        "Customers love it. Harrowfen is stale. Holiday sampler is $32 through December 31, 2025."
    ),
    "kestrune-cycles": (
        "An effortless ride that burns fat. Zero emissions and the fastest around. Only $999. "
        "Riders love it. Voltmere is unreliable. Save $200 on the Arc 7 through March 31, 2026."
    ),
}
EXPECTED_DIRTY = {
    "banned_word",
    "banned_claim_type",
    "health_claim",
    "environmental_claim",
    "superlative_claim",
    "pricing_claim",
    "testimonial_claim",
    "competitor_disparagement",
    "expired_fact",
}


def load(name: str) -> CampaignInputs:
    folder = EXAMPLES / name
    return load_campaign_inputs(
        folder / "brand.yaml", folder / "facts.yaml", folder / "product.yaml"
    )


def context(inputs: CampaignInputs) -> RuleContext:
    return RuleContext(brand=inputs.brand, facts=inputs.facts, today=TODAY)


@pytest.mark.parametrize("name", BRANDS)
def test_example_inputs_load_and_agree(name: str) -> None:
    inputs = load(name)
    assert len(inputs.facts.facts) >= 10
    assert inputs.brand.competitors


@pytest.mark.parametrize("name", BRANDS)
def test_fact_sheet_covers_regulated_types_and_an_expired_fact(name: str) -> None:
    facts = load(name).facts.facts
    assert {"pricing", "environmental", "superlative", "testimonial"} <= {
        fact.claim_type for fact in facts
    }
    assert [fact.id for fact in facts if fact.is_expired(TODAY)] == ["F-010"]


@pytest.mark.parametrize("name", BRANDS)
def test_examples_state_that_they_are_fictional(name: str) -> None:
    for file in ("brand.yaml", "facts.yaml", "product.yaml"):
        assert "Fictional" in (EXAMPLES / name / file).read_text()


@pytest.mark.parametrize("name", BRANDS)
def test_compliant_copy_passes(name: str) -> None:
    inputs = load(name)
    report = check_asset(CLEAN[name], context(inputs))
    assert report.violations == []


@pytest.mark.parametrize("name", BRANDS)
def test_non_compliant_copy_breaks_every_content_rule(name: str) -> None:
    inputs = load(name)
    copy = AssetCopy(asset_id="dirty", channel="email", fields={"body": DIRTY[name]})
    assert {v.rule for v in check_asset(copy, context(inputs)).violations} == EXPECTED_DIRTY


def test_harvest_fact_is_approved_until_the_end_of_2027() -> None:
    fact = load("tamsin-hollow-roasters").facts.get("F-011")
    assert fact.claim == "Hollow Reserve is roasted from beans harvested in 2026."
    assert fact.expires == date(2027, 12, 31)


def test_sample_campaign_leaves_out_raw_research() -> None:
    sample = EXAMPLES / "sample-campaign"
    assert (sample / "kit.json").is_file()
    assert not (sample / "research.json").exists()


def test_sample_campaign_is_an_approved_kit_that_shows_a_correct_rejection() -> None:
    kit = load_kit(EXAMPLES / "sample-campaign")
    assert (kit.status, kit.mode, kit.gaps) == ("approved", "team", [])
    assert kit.approval.content_sha256 == kit.content_sha256 == kit.compute_hash()
    assert unverified_statements(kit) == []
    assert {claim.verdict for claim in kit.claims} == {"supported"}
    assert [item.asset_id for item in kit.rejected_image_prompts] == ["instagram-1"]
    assert (
        "Internal planning, not for publication."
        in (EXAMPLES / "sample-campaign" / "kit.html").read_text()
    )
