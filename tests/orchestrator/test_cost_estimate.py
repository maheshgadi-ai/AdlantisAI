import pytest

from adlantis.config import Settings, load_profile
from adlantis.orchestrator.cost_estimate import (
    TAVILY_USD_PER_CREDIT,
    estimate_campaign_cost,
    estimate_research_cost,
)
from adlantis.schemas import ResearchLimits


def test_estimate_uses_the_researcher_model_and_search_budget() -> None:
    estimate = estimate_research_cost(load_profile("budget"), Settings())
    assert estimate.model == load_profile("budget").resolve("researcher", Settings()).label
    assert estimate.search_credits == 4
    assert estimate.search_usd == pytest.approx(4 * TAVILY_USD_PER_CREDIT)


def test_worst_case_covers_the_typical_run() -> None:
    estimate = estimate_research_cost(load_profile("budget"), Settings())
    assert 0 < estimate.typical_usd < estimate.worst_case_usd


def test_larger_limits_cost_more() -> None:
    models = load_profile("budget")
    small = estimate_research_cost(models, Settings(), ResearchLimits(max_turns=2))
    large = estimate_research_cost(models, Settings(), ResearchLimits(max_turns=16))
    assert large.worst_case_usd > small.worst_case_usd


def test_stronger_model_costs_more(monkeypatch: pytest.MonkeyPatch) -> None:
    models = load_profile("budget")
    cheap = estimate_research_cost(models, Settings())
    monkeypatch.setenv("MODEL__RESEARCHER", "openai:gpt-6.2-sol")
    assert estimate_research_cost(models, Settings()).worst_case_usd > cheap.worst_case_usd


def test_campaign_estimate_counts_every_planned_asset() -> None:
    estimate = estimate_campaign_cost(load_profile("budget"), Settings(), ["search_ad", "email"])
    assert estimate.assets == 4


def test_campaign_worst_case_covers_the_typical_run() -> None:
    estimate = estimate_campaign_cost(load_profile("budget"), Settings(), ["search_ad", "email"])
    assert 0 < estimate.typical_usd < estimate.worst_case_usd


def test_default_profile_campaign_costs_more_than_budget() -> None:
    channels = ["search_ad", "email"]
    budget = estimate_campaign_cost(load_profile("budget"), Settings(), channels)
    default = estimate_campaign_cost(load_profile("default"), Settings(), channels)
    assert default.worst_case_usd > budget.worst_case_usd


def test_more_revision_rounds_cost_more() -> None:
    models = load_profile("budget")
    one = estimate_campaign_cost(models, Settings(), ["email"], max_rounds=1)
    two = estimate_campaign_cost(models, Settings(), ["email"], max_rounds=2)
    assert two.worst_case_usd > one.worst_case_usd
