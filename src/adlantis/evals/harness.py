"""Runs an evaluation step by step, stopping before the budget can be passed."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from adlantis.evals.briefs import AdversarialBrief, apply_brief
from adlantis.evals.claim_severity import BadClaim, ClassifiedClaim
from adlantis.evals.metrics import RunMetrics, baseline_metrics, team_metrics
from adlantis.evals.pairwise import PairResult
from adlantis.evals.plan import (
    AUDIT_CAP_USD,
    BASELINE_CAP_USD,
    CHECKER_FLOOR_USD,
    JUDGE_CAP_USD,
    RECALL_CAP_USD,
    RUN_CAPS_USD,
    TRIAGE_CAP_USD,
    EvalPlan,
    selected_briefs,
)
from adlantis.evals.recall import RecallReport
from adlantis.schemas.claim_check import ClaimCheckResult
from adlantis.schemas.inputs import CampaignInputs
from adlantis.schemas.kit import CampaignKit


class EvalStopped(RuntimeError):
    """The remaining budget cannot cover the next step."""


class EvalResults(BaseModel):
    """Everything an evaluation measured, including how far it got."""

    tier: str
    eval_date: date
    cap_usd: float
    spent_usd: float = 0.0
    runs: list[RunMetrics] = Field(default_factory=list)
    pairs: list[PairResult] = Field(default_factory=list)
    recall: dict[str, RecallReport] = Field(default_factory=dict)
    stopped_reason: str | None = None


@dataclass(frozen=True)
class RunOutcome:
    """What one campaign or baseline run produced."""

    kit: CampaignKit | None
    cost_usd: float
    seconds: float
    withheld: tuple[str, ...] = ()
    error: str | None = None
    run_dir: str | None = None


@dataclass(frozen=True)
class EvalDeps:
    """The billed work. Tests replace each step with a fake."""

    run: Callable[[AdversarialBrief, CampaignInputs, str, bool, float], RunOutcome]
    audit: Callable[
        [CampaignKit, CampaignInputs, str, float],
        tuple[list[ClaimCheckResult], float, list[str]],
    ]
    judge: Callable[[CampaignKit, CampaignKit, CampaignInputs, str, int, str, float], PairResult]
    recall: Callable[[str, float], tuple[RecallReport, float]]
    triage: Callable[
        [CampaignInputs, list[BadClaim], str, float],
        tuple[list[ClassifiedClaim], float, str | None],
    ]


class EvalBudget:
    """The hard cap on a whole evaluation."""

    def __init__(self, cap_usd: float) -> None:
        self.cap_usd = cap_usd
        self.spent_usd = 0.0

    def allow(self, step_cap_usd: float, floor_usd: float | None = None) -> float:
        """The cap for the next step.

        With `floor_usd`, a step may run on whatever remains when that still covers one call.

        Raises:
            EvalStopped: If the step could pass the evaluation's cap.
        """
        remaining = self.cap_usd - self.spent_usd
        if floor_usd is not None and floor_usd <= remaining < step_cap_usd:
            return remaining
        if remaining < step_cap_usd:
            raise EvalStopped(
                f"${remaining:.2f} remains, and the next step may cost ${step_cap_usd:.2f}."
            )
        return step_cap_usd

    def spend(self, amount_usd: float) -> None:
        """Record what a finished step cost."""
        self.spent_usd += amount_usd


def classify(
    run: RunMetrics, inputs: CampaignInputs, deps: EvalDeps, budget: EvalBudget
) -> RunMetrics:
    """Have the checker read each rejected claim. A failure is recorded, never hidden."""
    if not run.bad_claim_details:
        return run
    classified, cost, error = deps.triage(
        inputs, run.bad_claim_details, run.profile, budget.allow(TRIAGE_CAP_USD, CHECKER_FLOOR_USD)
    )
    budget.spend(cost)
    update: dict = {"classified_claims": classified}
    if error:
        update["failure"] = f"Claim triage failed: {error}"
    return run.model_copy(update=update)


def team_result(
    brief: AdversarialBrief,
    inputs: CampaignInputs,
    outcome: RunOutcome,
    eval_date: date,
    **common: object,
) -> RunMetrics:
    """The metrics for one agent-team run, or a failed run with its reason."""
    timing = {
        "cost_usd": outcome.cost_usd,
        "seconds": outcome.seconds,
        "quarantine_expected": brief.expects_quarantine,
        "withheld_sources": list(outcome.withheld),
        "run_dir": outcome.run_dir,
    }
    if outcome.kit is None:
        return RunMetrics(
            brief_id=brief.id,
            mode="team",
            status="failed",
            failure=outcome.error,
            **common,
            **timing,
        )
    return team_metrics(brief, outcome.kit, inputs, eval_date, **common, **timing)


def _run_pair(
    brief: AdversarialBrief,
    inputs: CampaignInputs,
    profile: str,
    repeat: int,
    deps: EvalDeps,
    budget: EvalBudget,
    results: EvalResults,
) -> None:
    common = {"profile": profile, "repeat": repeat}
    team = deps.run(brief, inputs, profile, False, budget.allow(RUN_CAPS_USD[profile]))
    budget.spend(team.cost_usd)
    team_run = team_result(brief, inputs, team, results.eval_date, **common)
    results.runs.append(classify(team_run, inputs, deps, budget))
    base = deps.run(brief, inputs, profile, True, budget.allow(BASELINE_CAP_USD))
    budget.spend(base.cost_usd)
    timing = {"cost_usd": base.cost_usd, "seconds": base.seconds, "run_dir": base.run_dir}
    if base.kit is None:
        results.runs.append(
            RunMetrics(
                brief_id=brief.id,
                mode="baseline",
                status="failed",
                failure=base.error,
                **common,
                **timing,
            )
        )
        return
    audit, audit_cost, audit_errors = deps.audit(
        base.kit, inputs, profile, budget.allow(AUDIT_CAP_USD)
    )
    budget.spend(audit_cost)
    timing["cost_usd"] += audit_cost
    timing["audit_cost_usd"] = audit_cost
    base_run = baseline_metrics(
        brief, base.kit, audit, inputs, results.eval_date, **common, **timing
    )
    if audit_errors:
        reason = "The claim audit failed for " + "; ".join(audit_errors)
        base_run = base_run.model_copy(update={"status": "unaudited", "failure": reason})
    results.runs.append(classify(base_run, inputs, deps, budget))
    if team.kit is not None:
        pair = deps.judge(
            team.kit, base.kit, inputs, profile, repeat, brief.id, budget.allow(JUDGE_CAP_USD)
        )
        budget.spend(pair.cost_usd)
        results.pairs.append(pair)


def run_plan(
    plan: EvalPlan,
    briefs: Sequence[AdversarialBrief],
    deps: EvalDeps,
    cap_usd: float,
    eval_date: date,
    examples_dir: Path,
    on_progress: Callable[[EvalResults], None] = lambda _results: None,
) -> EvalResults:
    """Run the plan. Stopping early keeps every result measured so far."""
    budget = EvalBudget(cap_usd)
    results = EvalResults(tier=plan.name, eval_date=eval_date, cap_usd=cap_usd)
    try:
        chosen = [(b, apply_brief(b, examples_dir)) for b in selected_briefs(plan, briefs)]
        for profile, repeats in plan.repeats.items():
            for repeat in range(1, repeats + 1):  # a full pass first, so a cap stop leaves one
                for brief, inputs in chosen:
                    _run_pair(brief, inputs, profile, repeat, deps, budget, results)
                    results.spent_usd = budget.spent_usd
                    on_progress(results)
            report, cost = deps.recall(profile, budget.allow(RECALL_CAP_USD[profile]))
            budget.spend(cost)
            results.recall[profile] = report.model_copy(update={"cost_usd": cost})
    except EvalStopped as exc:
        results.stopped_reason = str(exc)
    results.spent_usd = budget.spent_usd
    on_progress(results)
    return results
