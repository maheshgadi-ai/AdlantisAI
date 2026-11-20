"""Search ads name the product, and research plans within its budget."""

from adlantis.agents import Copywriter
from adlantis.orchestrator.review_loop import ReviewContext, ReviewLoop
from adlantis.rules.channels import required_mentions
from adlantis.schemas import (
    AssetEdit,
    CampaignAsset,
    ClaimCheckResult,
    CopyRequest,
    ResearchLimits,
    RevisionPlan,
)
from tests.agents.copy_helpers import PRODUCT, STRATEGY, gpt, router
from tests.agents.research_helpers import BRIEF, Web, report, researcher, stop
from tests.orchestrator.test_review_loop import blocked
from tests.rules.helpers import SHEET, TODAY, brand


def search_variant(headline: str) -> dict:
    return {
        "fields": [
            {"name": "headline", "text": headline},
            {"name": "description", "text": "Slow mornings."},
        ],
        "citations": [],
    }


def write(*variants: dict):
    built, calls = router(openai=(gpt("submit_channel_draft", {"variants": list(variants)}),))
    request = CopyRequest(
        brand=brand(),
        product=PRODUCT,
        strategy=STRATEGY,
        facts=SHEET,
        channel="search_ad",
        today=TODAY,
    )
    return Copywriter(built).run(request), calls["openai"]


def test_search_headline_must_name_the_product() -> None:
    assert required_mentions("search_ad", "Hollow Reserve") == {"headline": "Hollow Reserve"}


def test_other_channels_have_no_required_name() -> None:
    assert required_mentions("email", "Hollow Reserve") == {}


def test_blank_product_name_requires_nothing() -> None:
    assert required_mentions("search_ad", " ") == {}


def test_name_too_long_for_a_headline_is_not_required() -> None:
    assert required_mentions("search_ad", "R" * 31) == {}


def test_name_that_exactly_fits_a_headline_is_required() -> None:
    assert required_mentions("search_ad", "R" * 30) == {"headline": "R" * 30}


def test_variant_without_the_product_name_is_rejected() -> None:
    result, _ = write(search_variant("Roasted to order"))
    assert result.assets == []
    assert result.rejected[0] == "Variant 1: must name the product in: ['headline']"


def test_variant_with_the_product_name_is_kept() -> None:
    result, calls = write(search_variant("Hollow Reserve Coffee"))
    assert [item.asset_id for item in result.assets] == ["search_ad-1"]
    assert "required_mentions" in str(calls[0]["input"])


class _Checker:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, data: CampaignAsset) -> ClaimCheckResult:
        self.calls += 1
        claims = [blocked(data.asset_id, "Coffee")] if self.calls == 1 else []
        return ClaimCheckResult(asset_id=data.asset_id, claims=claims)


class _Reviser:
    def __init__(self) -> None:
        self.request = None

    def revise(self, data) -> RevisionPlan:
        self.request = data
        edit = AssetEdit(
            issue_id=data.issues[0].id,
            field="headline",
            find="Hollow Reserve Coffee",
            replace="Roasted to order",
        )
        return RevisionPlan(edits=[edit])


def test_review_loop_protects_the_product_name_in_search_headlines() -> None:
    reviser = _Reviser()
    context = ReviewContext(
        brand=brand(),
        facts=SHEET,
        findings=[],
        today=TODAY,
        allowed_references=frozenset(),
        product_name="Hollow Reserve",
    )
    copy = CampaignAsset(
        asset_id="search_ad-1",
        channel="search_ad",
        fields={"headline": "Hollow Reserve Coffee", "description": "Slow mornings."},
    )
    outcome = ReviewLoop(_Checker(), reviser, context).review([copy])
    assert reviser.request.required_mentions == {"headline": "Hollow Reserve"}
    assert outcome.assets == []
    assert [gap.asset_id for gap in outcome.gaps] == ["search_ad-1"]


def test_research_brief_states_the_budget() -> None:
    limits = ResearchLimits(max_searches=3, max_fetches=2)
    agent, calls = researcher(Web(), stop(), report(), limits=limits)
    agent.run(BRIEF)
    assert "3 searches and 2 page reads" in str(calls[0]["input"])
