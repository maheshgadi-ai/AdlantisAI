"""One real research run. It costs money, so it needs two explicit opt-ins.

    ADLANTIS_RUN_LIVE_RESEARCH=1 pytest -m live -s tests/live/test_researcher_live.py

Without the environment variable it prints the cost estimate and skips.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from adlantis.agents import Researcher
from adlantis.config import get_settings, load_profile
from adlantis.llm import ModelRouter
from adlantis.orchestrator.cost_estimate import estimate_research_cost
from adlantis.schemas import (
    ResearchBrief,
    ResearchLimits,
    ResearchResult,
    load_campaign_inputs,
)
from adlantis.tools import SourceQualityScorer, build_default_registry
from adlantis.tools.untrusted import injection_matches, injection_signals, quote_appears_in

pytestmark = pytest.mark.live

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "tamsin-hollow-roasters"


def _print_withheld_pages(outcome: ResearchResult) -> None:
    """Show each withheld source and the exact words that triggered it, to judge false alarms."""
    withheld = outcome.evidence.quarantined()
    total = len(outcome.evidence.records)
    print(f"Withheld by the instruction detector: {len(withheld)} of {total} sources")
    for record in withheld:
        text = f"{record.url}\n{record.title}\n{record.excerpt}"
        print(f"- {record.id} {record.url}")
        for name, passage in injection_matches(text):
            print(f"    {name}: {passage!r}")
            start = text.lower().find(passage.lower())
            if start >= 0:
                print(
                    f"      in context: {text[max(0, start - 120) : start + len(passage) + 120]!r}"
                )


def test_one_research_run() -> None:
    settings = get_settings()
    models = load_profile("budget")
    limits = ResearchLimits()
    estimate = estimate_research_cost(models, settings, limits)
    print(
        f"\nResearch run on {estimate.model}: about ${estimate.typical_usd:.3f}, "
        f"at most ${estimate.worst_case_usd:.3f} "
        f"(includes {estimate.search_credits} search credits)."
    )
    if os.environ.get("ADLANTIS_RUN_LIVE_RESEARCH") != "1":
        pytest.skip("Set ADLANTIS_RUN_LIVE_RESEARCH=1 to run this billed test.")
    if not (settings.api_key("openai") and settings.tavily_api_key):
        pytest.skip("OPENAI_API_KEY and TAVILY_API_KEY are required.")

    limits = limits.model_copy(update={"max_cost_usd": estimate.worst_case_model_usd})
    inputs = load_campaign_inputs(
        EXAMPLE / "brand.yaml", EXAMPLE / "facts.yaml", EXAMPLE / "product.yaml"
    )
    router = ModelRouter.from_settings(settings, profile="budget")
    with build_default_registry(settings, tracer=router.tracer) as tools:
        agent = Researcher(router, tools, SourceQualityScorer.from_path(), limits)
        outcome = agent.run(ResearchBrief.from_campaign(inputs))

    print(f"Actual model cost: ${router.usage.cost_usd:.4f}")
    _print_withheld_pages(outcome)
    assert outcome.evidence.records, "the run should find sources"
    assert router.usage.cost_usd <= estimate.worst_case_model_usd
    for item in outcome.findings:
        cited = [outcome.evidence.get(evidence_id) for evidence_id in item.evidence_ids]
        assert all(record and record.status == "usable" for record in cited)
        assert any(quote_appears_in(item.supporting_quote, record.excerpt) for record in cited)
        assert injection_signals(item.statement) == ()
