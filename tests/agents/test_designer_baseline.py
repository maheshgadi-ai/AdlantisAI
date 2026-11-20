"""The designer's prompts pass code checks, and the baseline writes one unverified campaign."""

import json

import pytest

from adlantis.agents import BaselineAgent, Designer
from adlantis.config.images import load_image_config
from adlantis.prompts import load_prompt
from adlantis.rules.image_prompts import SAFETY_SUFFIX
from adlantis.schemas.baseline import BaselineDraft, BaselineRequest
from adlantis.schemas.design import DesignDraft, DesignRequest
from tests.agents.copy_helpers import PRODUCT, STRATEGY, asset, gpt, router
from tests.rules.helpers import SHEET, TODAY, brand


def design(*prompts: dict, assets=None):
    built, calls = router(openai=(gpt("submit_design_draft", {"prompts": list(prompts)}),))
    request = DesignRequest(
        brand=brand(),
        product=PRODUCT,
        strategy=STRATEGY,
        assets=[asset()] if assets is None else assets,
    )
    return Designer(built).run(request), calls["openai"]


def idea(**changes: object) -> dict:
    return {
        "asset_id": "email-1",
        "prompt": "A mug on an oak table in morning light.",
        "alt_text": "A mug on a table.",
    } | changes


def search_asset():
    return asset(asset_id="search_ad-1").model_copy(update={"channel": "search_ad"})


def test_designer_uses_its_low_cost_role() -> None:
    _, calls = design(idea())
    assert calls[0]["model"] == "gpt-6-luna"


def test_accepted_prompt_gets_the_safety_suffix_and_channel_size() -> None:
    result, _ = design(idea())
    prompt = result.prompts[0]
    assert prompt.prompt.endswith(SAFETY_SUFFIX)
    assert prompt.size == load_image_config().size_for("email")
    assert result.rejected == []


@pytest.mark.parametrize(
    "changes",
    [
        {"prompt": "A mug with our logo."},
        {"prompt": "A celebrity with a mug."},
        {"alt_text": "A Starbucks cup."},
        {"prompt": "A bag of Ridge Reserve by Harrowfen."},
    ],
)
def test_unsafe_prompt_is_rejected_with_a_reason(changes: dict) -> None:
    result, _ = design(idea(**changes))
    assert result.prompts == []
    assert result.rejected[0].asset_id == "email-1"
    assert result.rejected[0].reason


@pytest.mark.parametrize("changes", [{"prompt": "  "}, {"alt_text": " "}])
def test_empty_prompt_is_rejected(changes: dict) -> None:
    assert design(idea(**changes))[0].rejected[0].reason == (
        "the prompt or its description is empty"
    )


def test_asset_without_a_prompt_is_listed() -> None:
    assert design()[0].rejected[0].reason == "no prompt was returned"


def test_prompt_for_an_unknown_asset_is_ignored() -> None:
    result, _ = design(idea(asset_id="email-9"))
    assert result.prompts == []


def test_first_prompt_for_an_asset_wins() -> None:
    result, _ = design(idea(), idea(prompt="A kettle on a stove."))
    assert len(result.prompts) == 1 and "mug" in result.prompts[0].prompt


def test_text_only_channels_make_no_model_call() -> None:
    result, calls = design(assets=[search_asset()])
    assert (result.prompts, result.rejected, calls) == ([], [], [])


def test_designer_prompt_forbids_people_brands_and_logos() -> None:
    text = load_prompt("designer")
    assert all(word in text for word in ("recognizable person", "real company", "logo"))


def test_designer_schema_cannot_approve_anything() -> None:
    assert set(DesignDraft.model_fields) == {"prompts"}


def baseline(*channels: dict):
    draft = {"positioning": "Plain coffee.", "concept": "Know it.", "channels": list(channels)}
    built, calls = router(openai=(gpt("submit_baseline_draft", draft),))
    product = PRODUCT.model_copy(update={"channels": ["email"]})
    request = BaselineRequest(brand=brand(), product=product, facts=SHEET, today=TODAY)
    return BaselineAgent(built).run(request), calls["openai"]


def email(citation_refs: tuple[str, ...] = ("F-001",)) -> dict:
    text = "Roasted within 48 hours of shipping."
    return {
        "channel": "email",
        "variants": [
            {
                "fields": [
                    {"name": "subject", "text": "Harvest"},
                    {"name": "preheader", "text": "New"},
                    {"name": "body", "text": text},
                ],
                "citations": [{"text": text, "references": list(citation_refs)}],
            }
        ],
    }


def test_baseline_runs_once_on_the_copywriters_model() -> None:
    result, calls = baseline(email())
    assert (len(calls), calls[0]["model"]) == (1, "gpt-6.1-terra")
    assert [item.asset_id for item in result.assets] == ["email-1"]
    assert result.positioning == "Plain coffee."


def test_baseline_never_sees_expired_facts() -> None:
    _, calls = baseline(email())
    assert "Holiday bundle" not in json.dumps(calls[0]["input"])


def test_baseline_drops_citations_of_expired_facts() -> None:
    result, _ = baseline(email(("F-008",)))
    assert result.assets[0].citations == []


def test_baseline_reports_a_broken_variant() -> None:
    fields = [{"name": "headline", "text": "Wrong field"}]
    broken = {"channel": "email", "variants": [{"fields": fields, "citations": []}]}
    result, _ = baseline(broken)
    assert result.assets == [] and result.rejected[0].startswith("email: Variant 1")


def test_baseline_ignores_channels_outside_the_brief() -> None:
    result, _ = baseline({"channel": "x", "variants": []}, email())
    assert {item.channel for item in result.assets} == {"email"}


def test_baseline_schema_works_with_strict_outputs() -> None:
    assert "channels" in BaselineDraft.model_json_schema()["properties"]
