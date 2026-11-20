"""The evaluation stops before its cap and reports results whichever way they fall."""

from datetime import date

import pytest
from typer.testing import CliRunner

import adlantis.interfaces.cli as cli
import adlantis.interfaces.eval_cli as eval_cli
from adlantis.config import Settings
from adlantis.evals.claim_severity import ClassifiedClaim
from adlantis.evals.harness import (
    EvalBudget,
    EvalDeps,
    EvalResults,
    EvalStopped,
    RunOutcome,
    run_plan,
)
from adlantis.evals.metrics import RunMetrics
from adlantis.evals.plan import RUN_CAPS_USD, TIERS, EvalPlan, estimate_plan, selected_briefs
from adlantis.evals.recall import RecallReport
from adlantis.evals.report import render_report
from tests.evals.eval_helpers import BRIEFS, EXAMPLES, pair
from tests.orchestrator.kit_helpers import make_kit

DAY = date(2026, 11, 18)
SETTINGS = Settings(_env_file=None)
ONE = EvalPlan("one", ("AB-02",), {"budget": 1})


class Fake:
    """Scripted billed steps that record what they were asked to do."""

    def __init__(self, team=True, baseline=True, run_cost=0.5) -> None:
        self.team, self.baseline, self.run_cost = team, baseline, run_cost
        self.calls: list[str] = []
        self.audit_errors: list[str] = []
        self.caps: list[float] = []

    def run(self, brief, _inputs, profile, is_baseline, cap) -> RunOutcome:
        mode = "baseline" if is_baseline else "team"
        self.calls.append(f"{mode}:{brief.id}:{profile}")
        self.caps.append(cap)
        ok = self.baseline if is_baseline else self.team
        return RunOutcome(make_kit() if ok else None, self.run_cost, 10.0)

    def audit(self, _kit, _inputs, _profile, _cap):
        self.calls.append("audit")
        return [], 0.1, list(self.audit_errors)

    def triage(self, _inputs, claims, _profile, _cap):
        self.calls.append("triage")
        settled = [
            ClassifiedClaim(
                quote=c.quote, verdict=c.verdict, category="paraphrased_fact", cited=c.cited
            )
            for c in claims
        ]
        return settled, 0.01, None

    def judge(self, _team, _base, _inputs, profile, repeat, brief_id, _cap):
        self.calls.append("judge")
        return pair(brief_id=brief_id, profile=profile, repeat=repeat, cost_usd=0.05)

    def recall(self, profile, _cap):
        self.calls.append(f"recall:{profile}")
        return RecallReport(labeled_claims=2, found=2), 0.2

    def deps(self) -> EvalDeps:
        return EvalDeps(self.run, self.audit, self.judge, self.recall, self.triage)


def run(plan=ONE, fake=None, cap=50.0):
    fake = fake or Fake()
    return run_plan(plan, BRIEFS, fake.deps(), cap, DAY, EXAMPLES), fake


def test_steps_run_in_order() -> None:
    results, fake = run()
    assert fake.calls == [
        "team:AB-02:budget",
        "baseline:AB-02:budget",
        "audit",
        "judge",
        "recall:budget",
    ]
    assert [r.mode for r in results.runs] == ["team", "baseline"]


def test_spending_is_totaled() -> None:
    assert run()[0].spent_usd == pytest.approx(0.5 + 0.5 + 0.1 + 0.05 + 0.2)


def test_repeats_and_profiles_are_covered() -> None:
    plan = EvalPlan("two", ("AB-02",), {"budget": 2, "default": 1})
    results, _ = run(plan)
    assert [(r.profile, r.repeat) for r in results.runs if r.mode == "team"] == [
        ("budget", 1),
        ("budget", 2),
        ("default", 1),
    ]
    assert set(results.recall) == {"budget", "default"}


def test_every_brief_runs_once_before_any_repeat() -> None:
    plan = EvalPlan("two", ("AB-02", "AB-08"), {"budget": 2})
    results, _ = run(plan)
    team = [(r.brief_id, r.repeat) for r in results.runs if r.mode == "team"]
    assert team == [("AB-02", 1), ("AB-08", 1), ("AB-02", 2), ("AB-08", 2)]


def test_cap_stop_after_the_first_pass_keeps_every_brief() -> None:
    plan = EvalPlan("two", ("AB-02", "AB-08"), {"budget": 2})
    results, _ = run(plan, cap=3.2)
    first_pass = {r.brief_id for r in results.runs if r.mode == "team" and r.repeat == 1}
    assert first_pass == {"AB-02", "AB-08"} and results.stopped_reason


def test_run_caps_come_from_the_profile() -> None:
    _, fake = run()
    assert fake.caps[0] == RUN_CAPS_USD["budget"]


def test_evaluation_stops_before_a_step_that_could_pass_the_cap() -> None:
    results, fake = run(cap=0.75)
    assert fake.calls == []
    assert "next step may cost" in results.stopped_reason


def test_results_measured_before_stopping_are_kept() -> None:
    plan = EvalPlan("all", None, {"budget": 1})
    results, _ = run(plan, cap=3.0)
    assert results.runs and results.stopped_reason
    assert results.spent_usd <= 3.0


def test_budget_refuses_a_step_larger_than_what_remains() -> None:
    budget = EvalBudget(1.0)
    budget.spend(0.5)
    assert budget.allow(0.5) == 0.5
    with pytest.raises(EvalStopped):
        budget.allow(0.51)


def test_failed_team_run_is_recorded_and_not_judged() -> None:
    results, fake = run(fake=Fake(team=False))
    assert results.runs[0].status == "failed"
    assert "judge" not in fake.calls


def test_failed_baseline_run_is_recorded_and_not_audited() -> None:
    results, fake = run(fake=Fake(baseline=False))
    assert results.runs[1].status == "failed"
    assert "audit" not in fake.calls and "judge" not in fake.calls


def test_audit_cost_is_part_of_the_baseline_cost() -> None:
    assert run()[0].runs[1].cost_usd == pytest.approx(0.6)


def test_audit_and_recall_costs_are_recorded_separately() -> None:
    results = run()[0]
    assert results.runs[1].audit_cost_usd == pytest.approx(0.1)
    assert results.recall["budget"].cost_usd == pytest.approx(0.2)


def test_progress_is_saved_after_each_pair() -> None:
    seen: list[int] = []
    fake = Fake()
    run_plan(ONE, BRIEFS, fake.deps(), 50.0, DAY, EXAMPLES, lambda r: seen.append(len(r.runs)))
    assert seen[0] == 2


def metrics(mode: str = "team", **changes: object) -> RunMetrics:
    values = {"brief_id": "AB-02", "profile": "budget", "repeat": 1, "mode": mode}
    return RunMetrics(**{**values, **changes})


def report(*pairs, runs=None, **changes: object) -> str:
    return render_report(
        EvalResults(
            tier="standard",
            eval_date=DAY,
            cap_usd=41.0,
            runs=runs if runs is not None else [metrics(), metrics("baseline", unsupported=2)],
            pairs=list(pairs),
            **changes,
        )
    )


def test_report_states_the_date_plan_and_spending() -> None:
    text = report(pair(), spent_usd=20.0)
    assert "2026-11-18" in text and "`standard`" in text and "$20.00 of a $41.00" in text


def test_paired_rows_use_the_headline_count_for_both_systems() -> None:
    wording = ClassifiedClaim(
        quote="three tasting notes", verdict="unsupported", category="paraphrased_fact", cited=True
    )
    runs = [
        metrics(unsupported=1, classified_claims=[wording]),
        metrics("baseline", unsupported=1, classified_claims=[wording]),
    ]
    assert "| AB-02 | budget | 0.0 | 0.0 | +0.0 |" in report(pair(), runs=runs)


def test_report_says_when_the_team_wins() -> None:
    assert "The agent team won more comparisons." in report(pair("team"))


def test_report_says_when_the_baseline_wins() -> None:
    text = report(pair("baseline"), pair("baseline"), pair("team"))
    assert "The baseline won more comparisons." in text
    assert "the team won 1, the baseline won 2" in text


def test_an_even_result_is_called_inconclusive() -> None:
    assert "The judge result is inconclusive" in report(pair("team"), pair("baseline"))


def test_report_flags_a_team_kit_that_shipped_a_bad_claim() -> None:
    text = report(runs=[metrics(unsupported=1)])
    assert "**Requirement not met:** 1 agent-team runs" in text and "AB-02 (budget)" in text


def test_report_confirms_when_the_requirement_is_met() -> None:
    assert "**Requirement met:**" in report()


def test_baseline_bad_claims_do_not_fail_the_team_requirement() -> None:
    assert "**Requirement met:**" in report(runs=[metrics(), metrics("baseline", prohibited=5)])


def test_report_shows_paired_differences_by_brief() -> None:
    serious = ClassifiedClaim(
        quote="Paid fairly.", verdict="unsupported", category="fabricated_or_regulated", cited=False
    )
    runs = [metrics(), metrics("baseline", classified_claims=[serious, serious])]
    assert "| AB-02 | budget | 0.0 | 2.0 | -2.0 | +3.0 |" in report(pair(), runs=runs)


def test_report_counts_position_bias() -> None:
    assert "same position won both orders in 1 pairs" in report(pair("split", position_bias=True))


def test_report_discloses_an_early_stop_and_limitations() -> None:
    text = report(stopped_reason="$1.00 remains.")
    assert "Evaluation stopped early: $1.00 remains." in text and "## Limitations" in text


def test_report_shows_recall() -> None:
    text = report(recall={"budget": RecallReport(labeled_claims=4, found=3, correct_type=3)})
    assert "| budget | 4 | 3 | 75% | 100% |" in text


def test_tiers_grow_in_scope_and_cost() -> None:
    costs = [estimate_plan(TIERS[t], BRIEFS, SETTINGS).typical_usd for t in TIERS]
    assert 0 < costs[0] < costs[1] < costs[2]


def test_every_tier_after_smoke_uses_all_sixteen_briefs_and_both_profiles() -> None:
    for name in ("standard", "full"):
        assert len(selected_briefs(TIERS[name], BRIEFS)) == 16
        assert set(TIERS[name].repeats) == {"budget", "default"}


def test_estimate_lists_every_kind_of_billed_work() -> None:
    estimate = estimate_plan(TIERS["smoke"], BRIEFS, SETTINGS)
    assert {line.work for line in estimate.lines} == {
        "Agent team runs",
        "Baseline runs",
        "Baseline claim audits",
        "Blind judging, both orders",
        "Claim-extraction recall",
    }


def test_suggested_cap_leaves_room_above_the_expected_cost() -> None:
    estimate = estimate_plan(TIERS["standard"], BRIEFS, SETTINGS)
    assert estimate.suggested_cap_usd >= estimate.typical_usd * 1.5


runner = CliRunner()


@pytest.fixture
def no_billing(monkeypatch):
    calls = []
    monkeypatch.setattr(eval_cli, "live_deps", lambda *args: calls.append(args))
    monkeypatch.setattr(eval_cli, "run_plan", lambda *args, **kwargs: calls.append(args))
    return calls


def test_plan_command_shows_the_cost_without_keys_or_billing(no_billing) -> None:
    result = runner.invoke(cli.app, ["eval", "plan", "--tier", "smoke"])
    assert result.exit_code == 0, result.output
    assert "Expected cost" in result.output and "Suggested hard cap" in result.output
    assert no_billing == []


def test_run_needs_a_hard_cap(no_billing) -> None:
    assert runner.invoke(cli.app, ["eval", "run"]).exit_code != 0
    assert no_billing == []


def test_run_stops_when_keys_are_missing(no_billing, monkeypatch) -> None:
    monkeypatch.setattr(eval_cli, "get_settings", lambda: SETTINGS)
    result = runner.invoke(cli.app, ["eval", "run", "--max-cost", "3"], input="y\n")
    assert result.exit_code == 1 and "must both be set" in result.output
    assert no_billing == []


def test_run_shows_the_cost_and_stops_when_declined(no_billing, monkeypatch) -> None:
    keyed = Settings(_env_file=None, openai_api_key="k", anthropic_api_key="k")
    monkeypatch.setattr(eval_cli, "get_settings", lambda: keyed)
    result = runner.invoke(
        cli.app, ["eval", "run", "--max-cost", "3", "--tier", "smoke"], input="n\n"
    )
    assert result.exit_code == 0, result.output
    assert "Expected cost" in result.output and "Nothing was run." in result.output
    assert no_billing == []


def test_confirmed_run_writes_the_report(monkeypatch, tmp_path) -> None:
    keyed = Settings(_env_file=None, openai_api_key="k", anthropic_api_key="k")
    monkeypatch.setattr(eval_cli, "get_settings", lambda: keyed)
    monkeypatch.setattr(eval_cli, "live_deps", lambda *_args: None)
    done = EvalResults(tier="smoke", eval_date=DAY, cap_usd=3.0, spent_usd=1.0)
    monkeypatch.setattr(eval_cli, "run_plan", lambda *_args, **_kwargs: done)
    path = tmp_path / "report.md"
    args = ["eval", "run", "--max-cost", "3", "--tier", "smoke", "--report", str(path)]
    args += ["--outputs", str(tmp_path / "out")]
    result = runner.invoke(cli.app, args, input="y\n")
    assert result.exit_code == 0, result.output
    assert "# Evaluation results" in path.read_text()


class Failing(Fake):
    def run(self, brief, inputs, profile, is_baseline, cap) -> RunOutcome:
        if not is_baseline:
            self.calls.append(f"team:{brief.id}:{profile}")
            return RunOutcome(None, 0.03, 9.0, error="Anthropic request failed: credit too low")
        return super().run(brief, inputs, profile, is_baseline, cap)


def test_failed_team_run_records_its_reason() -> None:
    results, _ = run(fake=Failing())
    team = results.runs[0]
    assert (team.status, team.failure) == ("failed", "Anthropic request failed: credit too low")


def test_failed_audit_marks_the_baseline_unaudited_with_its_reason() -> None:
    fake = Fake()
    fake.audit_errors = ["email-1: credit too low"]
    baseline = run(fake=fake)[0].runs[1]
    assert baseline.status == "unaudited"
    assert baseline.failure == "The claim audit failed for email-1: credit too low"


def test_unaudited_baselines_are_left_out_of_claim_totals() -> None:
    runs = [metrics(), metrics("baseline", status="unaudited", unsupported=4)]
    assert "| budget | Single-prompt baseline | 1 | 0 |" in report(runs=runs)


def test_report_lists_every_failure_with_its_reason() -> None:
    runs = [metrics(status="failed", failure="credit too low"), metrics("baseline")]
    text = report(pair("no_comparison", error="judge timed out"), runs=runs)
    assert "AB-02, run 1, team: failed. credit too low" in text
    assert "AB-02, run 1, judge: judge timed out" in text


def test_report_lists_forbidden_phrases_with_their_context() -> None:
    runs = [
        metrics(),
        metrics("baseline", forbidden_contexts=["'breakfast' in: ...toast at breakfast..."]),
    ]
    assert "- AB-02, run 1, baseline: 'breakfast' in: ...toast at breakfast..." in report(runs=runs)


def test_report_calls_a_position_biased_result_inconclusive() -> None:
    pairs = [pair("baseline"), pair("team"), pair("split", position_bias=True)]
    assert "The judge result is inconclusive: 1 of 3 pairs" in report(*pairs)


def test_report_states_a_clear_winner_when_the_result_is_decisive() -> None:
    pairs = [pair("team"), pair("team"), pair("team"), pair("baseline")]
    assert "The agent team won more comparisons." in report(*pairs)
