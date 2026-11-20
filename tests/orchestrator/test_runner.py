"""A run saves its kit, log, and cost, and stops cleanly when it cannot finish."""

import json

import pytest

from adlantis.agents.strategist import StrategyError
from adlantis.config import Settings, load_profile
from adlantis.llm import ModelRouter
from adlantis.orchestrator import runner
from adlantis.orchestrator.kit_builder import KitBlocked
from adlantis.orchestrator.runner import (
    RunDependencies,
    RunFailed,
    RunRequest,
    estimate_run,
    start_run,
)
from adlantis.schemas import KeyMessage, StrategyResult
from adlantis.tools import ToolRegistry
from tests.agents.copy_helpers import gpt
from tests.fakes import fake_openai_client
from tests.orchestrator.kit_helpers import (
    INPUTS,
    NOW,
    STRATEGY,
    StubChecker,
    StubStrategist,
    stub_team,
)

SETTINGS = Settings(_env_file=None)


def request(tmp_path, **changes) -> RunRequest:
    return RunRequest(
        **{"inputs": INPUTS, "max_cost_usd": 1.0, "outputs_dir": tmp_path / "outputs", **changes}
    )


def deps(team=None, responses=()) -> RunDependencies:
    client = fake_openai_client(*responses)
    return RunDependencies(
        clock=lambda: NOW,
        make_router=lambda req, conf, trace: ModelRouter(
            conf,
            load_profile(req.profile),
            tracer=trace,
            client_factory=lambda _provider: client,
            max_cost_usd=req.max_cost_usd,
        ),
        make_tools=lambda _conf, _trace: ToolRegistry([]),
        make_team=lambda _router, _tools, _limits: team or stub_team(),
    )


def test_run_saves_a_draft_kit_with_its_log(tmp_path) -> None:
    output = start_run(request(tmp_path), SETTINGS, deps())
    assert output.run_dir.name == "20261118-120000-tamsin-hollow-roasters"
    assert {p.name for p in output.run_dir.iterdir()} == {
        "kit.json",
        "kit.md",
        "kit.html",
        "run_log.jsonl",
    }
    assert (output.kit.status, len(output.kit.assets)) == ("draft", 4)
    assert output.kit.research_gaps == ["No competitor data."]


def test_run_log_covers_the_whole_run(tmp_path) -> None:
    output = start_run(request(tmp_path), SETTINGS, deps())
    rows = [
        json.loads(line) for line in (output.run_dir / "run_log.jsonl").read_text().split("\n")[:-1]
    ]
    assert (rows[0]["stage"], rows[0]["status"]) == ("run", "started")
    assert (rows[-1]["stage"], rows[-1]["status"]) == ("run", "finished")


def test_kit_records_the_cap_and_search_spending(tmp_path) -> None:
    cost = start_run(request(tmp_path), SETTINGS, deps()).kit.cost
    assert (cost.cap_usd, cost.other_usd) == (1.0, pytest.approx(0.032))
    assert cost.total_usd == pytest.approx(cost.model_usd + cost.other_usd)


def test_two_runs_in_the_same_second_get_their_own_folders(tmp_path) -> None:
    first = start_run(request(tmp_path), SETTINGS, deps())
    second = start_run(request(tmp_path), SETTINGS, deps())
    assert first.run_dir != second.run_dir


def test_failed_run_keeps_its_log_and_writes_no_kit(tmp_path) -> None:
    team = stub_team(strategist=StubStrategist(StrategyError("no usable message")))
    with pytest.raises(RunFailed) as caught:
        start_run(request(tmp_path), SETTINGS, deps(team))
    run_dir = caught.value.run_dir
    assert not (run_dir / "kit.json").exists()
    last = json.loads((run_dir / "run_log.jsonl").read_text().splitlines()[-1])
    assert (last["stage"], last["status"]) == ("run", "failed")


def baseline_reply():
    text = "Every bag is roasted within 48 hours of shipping."
    variant = {
        "fields": [
            {"name": "subject", "text": "The best coffee ever"},
            {"name": "preheader", "text": "New"},
            {"name": "body", "text": text},
        ],
        "citations": [{"text": text, "references": ["F-001"]}],
    }
    return gpt(
        "submit_baseline_draft",
        {
            "positioning": "Plain coffee.",
            "concept": "Know it.",
            "channels": [{"channel": "email", "variants": [variant]}],
        },
    )


def test_baseline_run_is_unverified_and_reports_rule_problems(tmp_path) -> None:
    output = start_run(
        request(tmp_path, baseline=True), SETTINGS, deps(responses=[baseline_reply()])
    )
    kit = output.kit
    assert (kit.mode, kit.verified, kit.claims) == ("baseline", False, [])
    assert kit.summary == "Plain coffee. Know it."
    assert "superlative_claim" in {v.rule for item in kit.assets for v in item.warnings}


def test_baseline_failure_stops_the_run(tmp_path) -> None:
    with pytest.raises(RunFailed, match="baseline could not be produced"):
        start_run(
            request(tmp_path, baseline=True, max_cost_usd=0.0001),
            SETTINGS,
            deps(responses=[baseline_reply()]),
        )


def test_estimate_covers_the_typical_run(tmp_path) -> None:
    estimate = estimate_run(request(tmp_path), SETTINGS)
    assert 0 < estimate.typical_usd < estimate.worst_case_usd


def test_baseline_costs_less_than_the_team(tmp_path) -> None:
    team = estimate_run(request(tmp_path), SETTINGS)
    baseline = estimate_run(request(tmp_path, baseline=True), SETTINGS)
    assert baseline.worst_case_usd < team.worst_case_usd


def test_enabled_images_raise_the_estimate(tmp_path) -> None:
    off = estimate_run(request(tmp_path), SETTINGS)
    on = estimate_run(request(tmp_path), Settings(_env_file=None, enable_images=True))
    assert on.worst_case_usd == pytest.approx(off.worst_case_usd + 4 * 0.25)


def test_default_router_enforces_the_requested_cap(tmp_path) -> None:
    seen = []

    def make_team(router, _tools, _limits):
        seen.append(router)
        return stub_team()

    run_deps = RunDependencies(
        clock=lambda: NOW,
        make_tools=lambda _conf, _trace: ToolRegistry([]),
        make_team=make_team,
    )
    start_run(request(tmp_path, max_cost_usd=0.75), SETTINGS, run_deps)
    assert seen[0].budget.limit_usd == 0.75


def test_images_stay_off_unless_the_setting_is_on(tmp_path) -> None:
    output = start_run(request(tmp_path), SETTINGS, deps())
    log = (output.run_dir / "run_log.jsonl").read_text()
    assert "Image generation is off." in log and '"stage":"image:' not in log


def test_image_setting_reaches_the_pipeline(tmp_path) -> None:
    settings = Settings(_env_file=None, enable_images=True)
    output = start_run(request(tmp_path), settings, deps())
    assert '"stage":"image:email-1"' in (output.run_dir / "run_log.jsonl").read_text()


def test_removed_strategy_statement_is_listed_as_a_gap_in_the_kit(tmp_path) -> None:
    messages = [
        {"message": "Roasted within 48 hours of shipping.", "references": ["F-001"]},
        {"message": "Tastes of red apple.", "references": ["F-003"]},
    ]
    drafted = STRATEGY.model_copy(
        update={"key_messages": [KeyMessage.model_validate(item) for item in messages]}
    )

    class TwoMessages(StubStrategist):
        def run(self, _request) -> StrategyResult:
            return StrategyResult(strategy=drafted)

    team = stub_team(strategist=TwoMessages(), checker=StubChecker({"strategy-message-2"}))
    kit = start_run(request(tmp_path), SETTINGS, deps(team)).kit
    assert "strategy-message-2" in {gap.asset_id for gap in kit.gaps}
    assert [m.message for m in kit.strategy.key_messages] == [messages[0]["message"]]


def test_blocked_kit_stops_the_run_and_is_logged(tmp_path, monkeypatch) -> None:
    def blocked(_parts):
        raise KitBlocked("A section did not pass verification.")

    monkeypatch.setattr(runner, "build_team_kit", blocked)
    with pytest.raises(RunFailed, match="did not pass verification") as caught:
        start_run(request(tmp_path), SETTINGS, deps())
    assert not (caught.value.run_dir / "kit.json").exists()
