"""The `adlantis eval` commands."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import typer

from adlantis.config import ConfigurationError, enforce_role_rules, get_settings, load_profile
from adlantis.evals.briefs import load_briefs
from adlantis.evals.completion import (
    complete_failed_runs,
    failed_team_runs,
    unaudited_baselines,
    unjudged_pairs,
)
from adlantis.evals.harness import EvalResults, run_plan
from adlantis.evals.live import live_deps
from adlantis.evals.plan import TIERS, PlanEstimate, estimate_plan
from adlantis.evals.report import render_report
from adlantis.evals.rescore import rescore

eval_app = typer.Typer(help="Measure the agent team against adversarial briefs and a baseline.")
Tier = Literal["smoke", "budget", "standard", "full"]


def _show(estimate: PlanEstimate) -> None:
    typer.echo(f"Plan: {estimate.tier}, {estimate.briefs} briefs")
    for line in estimate.lines:
        typer.echo(f"  {line.profile:<8} {line.work:<28} {line.calls:>4} runs  ${line.usd:>7.2f}")
    typer.echo(f"Expected cost: ${estimate.typical_usd:.2f}")
    typer.echo(f"Suggested hard cap: ${estimate.suggested_cap_usd:.2f}")


@eval_app.command("plan")
def plan_command(
    tier: Annotated[Tier, typer.Option(help="smoke, budget, standard, or full.")] = "standard",
):
    """Show what an evaluation would run and cost. Nothing is billed."""
    _show(estimate_plan(TIERS[tier], load_briefs(), get_settings()))


def _keys_or_exit(settings) -> None:
    if not (settings.api_key("openai") and settings.api_key("anthropic")):
        typer.echo("Error: OPENAI_API_KEY and ANTHROPIC_API_KEY must both be set.", err=True)
        raise typer.Exit(code=1)


def _confirm(message: str) -> None:
    if not typer.confirm(message):
        typer.echo("Nothing was run.")
        raise typer.Exit


@eval_app.command("rescore")
def rescore_command(
    results: Annotated[Path, typer.Argument(help="A saved results JSON file.")],
    max_cost: Annotated[float, typer.Option("--max-cost", min=0.01, help="Hard cap in USD.")],
    report: Annotated[Path, typer.Option(help="Where to write the report.")] = Path(
        "evals/results/report.md"
    ),
    examples: Annotated[Path, typer.Option(help="Folder of example brands.")] = Path("examples"),
) -> None:
    """Re-score saved results. Only the claim checker's triage of rejected claims is billed."""
    settings = get_settings()
    _keys_or_exit(settings)
    saved = EvalResults.model_validate_json(results.read_text(encoding="utf-8"))
    batches = sum(bool(run.bad_claims) for run in saved.runs)
    typer.echo(f"Claim triage: {batches} checker calls, about ${batches * 0.02:.2f}.")
    typer.echo(f"Hard cap for this re-score: ${max_cost:.2f}")
    _confirm("Start this billed re-score?")
    today = saved.eval_date
    deps = live_deps(settings, results.parent, examples, today)
    scored = rescore(saved, load_briefs(), results.parent, examples, deps, max_cost)
    results.with_name("rescored.json").write_text(
        scored.model_dump_json(indent=2), encoding="utf-8"
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(scored), encoding="utf-8")
    typer.echo(f"Report: {report}")


@eval_app.command("complete")
def complete_command(
    results: Annotated[Path, typer.Argument(help="A saved results JSON file.")],
    max_cost: Annotated[float, typer.Option("--max-cost", min=0.01, help="Hard cap in USD.")],
    examples: Annotated[Path, typer.Option(help="Folder of example brands.")] = Path("examples"),
    report: Annotated[Path, typer.Option(help="Where to write the report.")] = Path(
        "evals/results/report.md"
    ),
) -> None:
    """Re-run failed team runs, re-audit unaudited baselines, and judge any missing pair."""
    settings = get_settings()
    _keys_or_exit(settings)
    saved = EvalResults.model_validate_json(results.read_text(encoding="utf-8"))
    failed = failed_team_runs(saved)
    unjudged = unjudged_pairs(saved)
    names = ", ".join(f"{brief} run {repeat}" for brief, _profile, repeat in failed)
    typer.echo(f"Failed agent-team runs: {names or 'none'}")
    unaudited = unaudited_baselines(saved)
    typer.echo(f"Pairs without a comparison: {len(unjudged)} or more after re-runs")
    typer.echo(f"Baselines to re-audit: {len(unaudited)}")
    typer.echo(f"Hard cap: ${max_cost:.2f}")
    if not failed and not unjudged and not unaudited:
        raise typer.Exit
    _confirm("Re-run these billed runs?")
    deps = live_deps(settings, results.parent, examples, saved.eval_date)
    done = complete_failed_runs(saved, load_briefs(), deps, max_cost, results.parent, examples)
    results.with_name("completed.json").write_text(done.model_dump_json(indent=2), encoding="utf-8")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(done), encoding="utf-8")
    typer.echo(f"Spent ${done.spent_usd - saved.spent_usd:.2f}. Saved completed.json and {report}.")


@eval_app.command("run")
def run_command(
    max_cost: Annotated[float, typer.Option("--max-cost", min=0.01, help="Hard cap in USD.")],
    tier: Annotated[Tier, typer.Option(help="smoke, budget, standard, or full.")] = "standard",
    outputs: Annotated[Path, typer.Option(help="Scratch folder for run outputs.")] = Path(
        "outputs/evals"
    ),
    report: Annotated[Path, typer.Option(help="Where to write the report.")] = Path(
        "evals/results/report.md"
    ),
    examples: Annotated[Path, typer.Option(help="Folder of example brands.")] = Path("examples"),
) -> None:
    """Run a billed evaluation after showing its cost and asking for confirmation."""
    settings = get_settings()
    plan, briefs = TIERS[tier], load_briefs()
    try:
        for profile in plan.repeats:
            enforce_role_rules(load_profile(profile), settings)
        if not (settings.api_key("openai") and settings.api_key("anthropic")):
            raise ConfigurationError("OPENAI_API_KEY and ANTHROPIC_API_KEY must both be set.")
    except ConfigurationError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _show(estimate_plan(plan, briefs, settings))
    typer.echo(f"Hard cap for this run: ${max_cost:.2f}")
    if not typer.confirm("Start this billed evaluation?"):
        typer.echo("Nothing was run.")
        raise typer.Exit
    today = date.today()
    deps = live_deps(settings, outputs / today.isoformat(), examples, today)
    raw = outputs / today.isoformat() / "results.json"
    raw.parent.mkdir(parents=True, exist_ok=True)

    def save(latest: EvalResults) -> None:
        raw.write_text(latest.model_dump_json(indent=2), encoding="utf-8")

    results = run_plan(plan, briefs, deps, max_cost, today, examples, on_progress=save)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(results), encoding="utf-8")
    typer.echo(f"Spent ${results.spent_usd:.2f}. Report: {report}")
