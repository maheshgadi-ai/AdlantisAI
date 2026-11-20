from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from adlantis.schemas import (
    ALL_CLAIM_TYPES,
    BANNABLE_CLAIM_TYPES,
    CLAIM_TAXONOMY,
    ApprovedFact,
    BrandKit,
    CampaignInputs,
    FactSheet,
    InputFileError,
    ProductBrief,
    load_yaml_model,
)
from tests.rules.helpers import brand, fact


def product(**changes: object) -> ProductBrief:
    values = {
        "name": "Reserve",
        "description": "A coffee.",
        "price_point": "$19",
        "target_market": "Home brewers",
        "campaign_goals": ["Launch"],
        "channels": ["email"],
    }
    return ProductBrief.model_validate({**values, **changes})


def test_taxonomy_covers_exactly_the_spec_types() -> None:
    assert set(ALL_CLAIM_TYPES) == {
        "product_fact",
        "statistic",
        "comparison",
        "superlative",
        "health",
        "environmental",
        "pricing",
        "testimonial",
        "other",
    }
    assert set(CLAIM_TAXONOMY) == set(ALL_CLAIM_TYPES)


def test_regulated_types_are_the_spec_categories() -> None:
    regulated = {t for t, category in CLAIM_TAXONOMY.items() if category.regulated}
    assert regulated == {"superlative", "health", "environmental", "pricing", "testimonial"}


@pytest.mark.parametrize("claim_type", ["product_fact", "other"])
def test_types_code_cannot_detect_cannot_be_banned(claim_type: str) -> None:
    assert claim_type not in BANNABLE_CLAIM_TYPES
    with pytest.raises(ValidationError, match="cannot be banned"):
        brand(banned_claim_types=[claim_type])


def test_unknown_brand_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="slogan"):
        brand(slogan="Hello")


def test_invalid_color_is_rejected() -> None:
    with pytest.raises(ValidationError, match="hex"):
        brand(colors=[{"name": "Moss", "hex": "green"}])


def test_blank_banned_word_is_rejected() -> None:
    with pytest.raises(ValidationError, match="blank"):
        brand(banned_words=["  "])


@pytest.mark.parametrize("fact_id", ["1", "F-1", "f-001", "F-0001"])
def test_malformed_fact_id_is_rejected(fact_id: str) -> None:
    with pytest.raises(ValidationError, match="id"):
        fact(fact_id, "other", "A claim.")


def test_fact_requires_an_evidence_note() -> None:
    with pytest.raises(ValidationError, match="evidence_note"):
        ApprovedFact(id="F-001", claim_type="other", claim="A claim.")


def test_exact_wording_cannot_have_paraphrases() -> None:
    with pytest.raises(ValidationError, match="exact wording"):
        fact("F-001", "other", "A claim.", approved_phrasings=["Claim."])


def test_paraphrase_requires_a_scope() -> None:
    with pytest.raises(ValidationError, match="paraphrase_scope"):
        fact("F-001", "other", "A claim.", wording="paraphrase")


def test_phrasing_cannot_invent_a_number() -> None:
    with pytest.raises(ValidationError, match="adds numbers"):
        fact(
            "F-001",
            "other",
            "Lasts 40 miles.",
            wording="paraphrase",
            paraphrase_scope="Keep the range.",
            approved_phrasings=["Lasts 60 miles."],
        )


def test_duplicate_fact_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate fact IDs"):
        FactSheet(facts=[fact("F-001", "other", "A."), fact("F-001", "other", "B.")])


def test_expiry_is_inclusive() -> None:
    dated = fact("F-001", "other", "A.", expires=date(2026, 6, 1))
    assert not dated.is_expired(date(2026, 6, 1))
    assert dated.is_expired(date(2026, 6, 2))


def test_unknown_channel_is_rejected() -> None:
    with pytest.raises(ValidationError, match="channels"):
        product(channels=["billboard"])


def test_repeated_channel_is_rejected() -> None:
    with pytest.raises(ValidationError, match="repeat"):
        product(channels=["email", "email"])


def test_product_requires_a_goal() -> None:
    with pytest.raises(ValidationError, match="campaign_goals"):
        product(campaign_goals=[])


def test_fact_of_a_banned_type_is_inconsistent() -> None:
    sheet = FactSheet(facts=[fact("F-001", "health", "Calming.")])
    with pytest.raises(ValidationError, match="banned claim type"):
        CampaignInputs(brand=brand(banned_claim_types=["health"]), facts=sheet, product=product())


def test_fact_using_a_banned_word_is_inconsistent() -> None:
    sheet = FactSheet(facts=[fact("F-001", "other", "A miracle roast.")])
    with pytest.raises(ValidationError, match="banned word"):
        CampaignInputs(brand=brand(), facts=sheet, product=product())


def test_brand_listed_as_its_own_competitor_is_inconsistent() -> None:
    kit = brand(competitors=[{"name": "Sample Roasters"}])
    with pytest.raises(ValidationError, match="the brand itself"):
        CampaignInputs(brand=kit, facts=FactSheet(), product=product())


def test_missing_file_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(InputFileError, match="not found"):
        load_yaml_model(tmp_path / "brand.yaml", BrandKit)


def test_malformed_yaml_is_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "brand.yaml"
    path.write_text("name: [unclosed")
    with pytest.raises(InputFileError, match="Invalid BrandKit"):
        load_yaml_model(path, BrandKit)


def test_invalid_contents_are_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "facts.yaml"
    path.write_text("facts:\n  - id: nope\n")
    with pytest.raises(InputFileError, match="Invalid FactSheet"):
        load_yaml_model(path, FactSheet)
