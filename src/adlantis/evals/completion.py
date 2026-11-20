"""Re-runs failed agent-team runs and judges any pair that is still missing a comparison."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from adlantis.evals.briefs import AdversarialBrief, apply_brief
from adlantis.evals.harness import (
    EvalBudget,
    EvalDeps,
    EvalResults,
    EvalStopped,
    classify,
    team_result,
)
from adlantis.evals.metrics import RunMetrics, baseline_metrics
from adlantis.evals.pairwise import PairResult
from adlantis.evals.plan import (
    AUDIT_CAP_USD,
    CHECKER_FLOOR_USD,
    JUDGE_FLOOR_USD,
    RERUN_JUDGE_CAP_USD,
    RERUN_TEAM_CAP_USD,
)
from adlantis.evals.rescore import run_kit

Key = tuple[str, str, int]


def failed_team_runs(results: EvalResults) -> list[Key]:
    """The brief, profile, and repeat of every agent-team run that produced no kit."""
    return [
        (run.brief_id, run.profile, run.repeat)
        for run in results.runs
        if run.mode == "team" and run.status == "failed"
    ]


def _run(runs: list[RunMetrics], key: Key, mode: str) -> RunMetrics | None:
    return next(
        (r for r in runs if (r.brief_id, r.profile, r.repeat, r.mode) == (*key, mode)), None
    )


def unjudged_pairs(results: EvalResults) -> list[Key]:
    """Pairs with an agent-team kit and a baseline kit that still lack a comparison."""
    judged = {
        (p.brief_id, p.profile, p.repeat) for p in results.pairs if p.outcome != "no_comparison"
    }
    keys = [
        (run.brief_id, run.profile, run.repeat)
        for run in results.runs
        if run.mode == "team" and run.status == "ok"
    ]
    return [
        key
        for key in keys
        if key not in judged
        and (base := _run(results.runs, key, "baseline")) is not None
        and base.status != "failed"
    ]


def unaudited_baselines(results: EvalResults) -> list[Key]:
    """Baselines whose claim audit did not complete."""
    return [
        (run.brief_id, run.profile, run.repeat)
        for run in results.runs
        if run.mode == "baseline" and run.status == "unaudited"
    ]


def _reaudit(
    results: EvalResults,
    runs: list[RunMetrics],
    key: Key,
    brief: AdversarialBrief,
    root: Path,
    examples_dir: Path,
    deps: EvalDeps,
    budget: EvalBudget,
) -> list[RunMetrics]:
    old = _run(runs, key, "baseline")
    kit = run_kit(old, root) if old else None
    if old is None or kit is None:
        return runs
    inputs = apply_brief(brief, examples_dir)
    audit, cost, errors = deps.audit(
        kit, inputs, key[1], budget.allow(AUDIT_CAP_USD, CHECKER_FLOOR_USD)
    )
    budget.spend(cost)
    keep = {"seconds": old.seconds, "run_dir": old.run_dir, "repeat": old.repeat}
    fresh = baseline_metrics(
        brief,
        kit,
        audit,
        inputs,
        results.eval_date,
        profile=old.profile,
        cost_usd=old.cost_usd + cost,
        audit_cost_usd=cost,
        **keep,
    )
    if errors:
        reason = "The claim audit failed for " + "; ".join(errors)
        fresh = fresh.model_copy(update={"status": "unaudited", "failure": reason})
    fresh = classify(fresh, inputs, deps, budget)
    return [
        fresh if (r.brief_id, r.profile, r.repeat, r.mode) == (*key, "baseline") else r
        for r in runs
    ]


def _rerun(
    results: EvalResults,
    runs: list[RunMetrics],
    key: Key,
    brief: AdversarialBrief,
    examples_dir: Path,
    deps: EvalDeps,
    budget: EvalBudget,
) -> list[RunMetrics]:
    _brief_id, profile, repeat = key
    inputs = apply_brief(brief, examples_dir)
    outcome = deps.run(brief, inputs, profile, False, budget.allow(RERUN_TEAM_CAP_USD))
    budget.spend(outcome.cost_usd)
    common = {"profile": profile, "repeat": repeat}
    fresh = team_result(brief, inputs, outcome, results.eval_date, **common)
    fresh = classify(fresh, inputs, deps, budget)
    return [
        fresh if (r.brief_id, r.profile, r.repeat, r.mode) == (*key, "team") else r for r in runs
    ]


def _judge(
    runs: list[RunMetrics],
    key: Key,
    brief: AdversarialBrief,
    root: Path,
    examples_dir: Path,
    deps: EvalDeps,
    budget: EvalBudget,
) -> PairResult | None:
    team, base = _run(runs, key, "team"), _run(runs, key, "baseline")
    team_kit = run_kit(team, root) if team else None
    base_kit = run_kit(base, root) if base else None
    if team_kit is None or base_kit is None:
        return None
    brief_id, profile, repeat = key
    pair = deps.judge(
        team_kit,
        base_kit,
        apply_brief(brief, examples_dir),
        profile,
        repeat,
        brief_id,
        budget.allow(RERUN_JUDGE_CAP_USD, JUDGE_FLOOR_USD),
    )
    budget.spend(pair.cost_usd)
    return pair


def complete_failed_runs(
    results: EvalResults,
    briefs: Sequence[AdversarialBrief],
    deps: EvalDeps,
    cap_usd: float,
    root: Path,
    examples_dir: Path,
) -> EvalResults:
    """Re-run failed team runs, re-audit unaudited baselines, then judge any missing pair."""
    by_id = {brief.id: brief for brief in briefs}
    budget = EvalBudget(cap_usd)
    runs, pairs = list(results.runs), list(results.pairs)
    stopped = None
    try:
        for key in failed_team_runs(results):
            runs = _rerun(results, runs, key, by_id[key[0]], examples_dir, deps, budget)
        for key in unaudited_baselines(results):
            runs = _reaudit(results, runs, key, by_id[key[0]], root, examples_dir, deps, budget)
        current = results.model_copy(update={"runs": runs, "pairs": pairs})
        for key in unjudged_pairs(current):
            pair = _judge(runs, key, by_id[key[0]], root, examples_dir, deps, budget)
            if pair is not None:
                pairs = [p for p in pairs if (p.brief_id, p.profile, p.repeat) != key] + [pair]
    except EvalStopped as exc:
        stopped = f"Completion stopped: {exc}"
    return results.model_copy(
        update={
            "runs": runs,
            "pairs": pairs,
            "spent_usd": results.spent_usd + budget.spent_usd,
            "stopped_reason": stopped or results.stopped_reason,
        }
    )
