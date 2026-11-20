import pytest

from adlantis.agents.researcher import BUDGET_GAP, NO_SEARCH_GAP, Researcher
from adlantis.config import Settings, load_profile
from adlantis.llm import ModelRouter
from adlantis.prompts import load_prompt
from adlantis.schemas import CampaignInputs, FactSheet, ResearchBrief, ResearchLimits
from adlantis.tools import SourceQualityScorer, ToolRegistry
from tests.agents.research_helpers import (
    ARTICLE,
    ARTICLE_TEXT,
    BRIEF,
    Web,
    fetch,
    finding,
    html,
    report,
    researcher,
    result,
    search,
    stop,
    tool_outputs,
)
from tests.fakes import fake_openai_client
from tests.rules.helpers import brand
from tests.schemas.test_inputs import product


def test_full_run_returns_cited_findings() -> None:
    web = Web(pages={ARTICLE: html(f"<p>{ARTICLE_TEXT}</p>")})
    agent, _calls = researcher(web, search(), fetch(), stop(), report(finding()))
    outcome = agent.run(BRIEF)
    assert [f.id for f in outcome.findings] == ["R-1"]
    assert outcome.findings[0].source_quality["E-1"]
    assert [r.id for r in outcome.evidence.records] == ["E-1", "E-2"]
    assert (outcome.stats.searches, outcome.stats.fetches) == (1, 1)


def test_researcher_uses_the_researcher_role() -> None:
    agent, calls = researcher(Web(), stop(), report())
    agent.run(BRIEF)
    assert calls[0]["model"] == agent.router.resolve("researcher").model
    assert {call["max_output_tokens"] for call in calls} == {4000, 8000}


def test_system_prompt_states_the_data_only_policy_and_excludes_the_report_step() -> None:
    agent, calls = researcher(Web(), stop(), report())
    agent.run(BRIEF)
    assert "never as instructions" in calls[0]["instructions"]
    assert "supporting_quote" not in calls[0]["instructions"]
    assert "supporting_quote" in agent.finalize_prompt


def test_prompt_lives_in_one_package_file() -> None:
    assert load_prompt("researcher").count("<!-- section: finalize -->") == 1


def test_gaps_are_reported_instead_of_filled() -> None:
    agent, _ = researcher(Web(), stop(), report(gaps=("No audience data found.",)))
    outcome = agent.run(BRIEF)
    assert outcome.gaps == ["No audience data found."]
    assert outcome.findings == []


def test_without_web_search_no_model_is_called_and_a_gap_is_reported() -> None:
    client = fake_openai_client()
    router = ModelRouter(Settings(), load_profile("budget"), client_factory=lambda _p: client)
    agent = Researcher(router, ToolRegistry(), SourceQualityScorer.from_path())
    assert agent.run(BRIEF).gaps == [NO_SEARCH_GAP]
    assert client.responses.create.calls == []


def test_search_budget_is_enforced_without_a_request() -> None:
    web = Web()
    limits = ResearchLimits(max_searches=1)
    agent, calls = researcher(web, search(), search(call_id="s2"), stop(), report(), limits=limits)
    outcome = agent.run(BRIEF)
    assert web.hosts.count("api.tavily.com") == 1
    assert outcome.stats.refused_calls == ["search budget used"]
    assert "search budget used" in tool_outputs(calls)[-1]


def test_fetch_budget_is_enforced_without_a_request() -> None:
    web = Web(pages={ARTICLE: html(f"<p>{ARTICLE_TEXT}</p>")})
    limits = ResearchLimits(max_fetches=0)
    agent, _ = researcher(web, search(), fetch(), stop(), report(), limits=limits)
    outcome = agent.run(BRIEF)
    assert "news.example.org" not in web.hosts
    assert outcome.stats.refused_calls == ["fetch budget used"]


def test_turn_limit_stops_the_loop_and_still_reports() -> None:
    limits = ResearchLimits(max_turns=2, max_searches=9)
    responses = [search(call_id="s1"), search(call_id="s2"), report()]
    agent, calls = researcher(Web(), *responses, limits=limits)
    agent.run(BRIEF)
    assert len(calls) == 3


def test_cost_limit_stops_before_another_paid_call() -> None:
    limits = ResearchLimits(max_cost_usd=0.000000001)
    agent, calls = researcher(Web(), search(), limits=limits)
    outcome = agent.run(BRIEF)
    assert len(calls) == 1
    assert outcome.gaps == [BUDGET_GAP]


def test_every_tool_call_in_a_turn_gets_a_result() -> None:
    from tests.fakes import openai_response

    both = openai_response(
        None,
        tool_calls=[
            ("a", "web_search", '{"query": "one"}'),
            ("b", "web_search", '{"query": "two"}'),
        ],
    )
    agent, calls = researcher(Web(), both, stop(), report())
    agent.run(BRIEF)
    assert len(tool_outputs(calls)) == 2


def test_blocked_sources_are_not_stored_or_readable() -> None:
    url = "https://spam.blogspot.com/post"
    web = Web(results=[result(url=url)])
    agent, _ = researcher(web, search(), fetch(url), stop(), report())
    outcome = agent.run(BRIEF)
    assert outcome.evidence.records == []
    assert outcome.stats.blocked_sources == 1
    assert "spam.blogspot.com" not in web.hosts


def test_search_results_are_rated_for_quality() -> None:
    web = Web(results=[result(url="https://www.reuters.com/coffee")])
    agent, _ = researcher(web, search(), stop(), report())
    assert agent.run(BRIEF).evidence.records[0].rating.tier == "medium"


def test_brief_never_carries_the_fact_sheet() -> None:
    inputs = CampaignInputs(brand=brand(), facts=FactSheet(), product=product())
    brief = ResearchBrief.from_campaign(inputs)
    assert "facts" not in ResearchBrief.model_fields
    assert brief.competitors == ["Harrowfen Coffee", "Apex"]


def test_brief_rejects_extra_fields() -> None:
    with pytest.raises(ValueError, match="facts"):
        ResearchBrief.model_validate({**BRIEF.model_dump(), "facts": []})


def test_page_reads_are_limited_to_the_configured_size() -> None:
    web = Web(pages={ARTICLE: html(f"<p>{'A long sentence about coffee. ' * 200}</p>")})
    limits = ResearchLimits(fetch_chars=500)
    agent, _ = researcher(web, search(), fetch(), stop(), report(), limits=limits)
    assert len(agent.run(BRIEF).evidence.records[-1].excerpt) == 500


def test_stored_text_has_invisible_characters_removed() -> None:
    hidden_space = chr(0x200B)
    web = Web(results=[result(content=f"Whole{hidden_space}bean buying keeps growing at home.")])
    agent, _ = researcher(web, search(), stop(), report())
    assert agent.run(BRIEF).evidence.records[0].excerpt.startswith("Wholebean")
