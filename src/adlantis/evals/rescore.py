"""Re-scores saved results from their kits. Claim triage is the only billed step."""

from __future__ import annotations

from pathlib import Path

from adlantis.evals.briefs import AdversarialBrief, apply_brief
from adlantis.evals.claim_severity import BadClaim
from adlantis.evals.harness import EvalBudget, EvalDeps, EvalResults, EvalStopped, classify
from adlantis.evals.metrics import RunMetrics, shipped_text
from adlantis.orchestrator.kit_store import load_kit
from adlantis.rules.text import contains_text
from adlantis.schemas.kit import CampaignKit

UNAUDITED = "The claim audit did not run, so its claims were never counted."


def run_kit(run: RunMetrics, root: Path) -> CampaignKit | None:
    """The saved kit behind a run, or None when the run produced no kit."""
    if run.run_dir:
        folder = Path(run.run_dir)
        return load_kit(folder) if (folder / "kit.json").is_file() else None
    folders = sorted(path for path in (root / run.brief_id).iterdir() if path.is_dir())
    kits = [load_kit(folder) for folder in folders if (folder / "kit.json").is_file()]
    matching = [kit for kit in kits if kit.mode == run.mode and kit.profile == run.profile]
    return matching[run.repeat - 1] if len(matching) >= run.repeat else None


def _cited_in(quote: str, kit: CampaignKit) -> bool:
    return any(
        contains_text(citation.text, quote) or contains_text(quote, citation.text)
        for item in kit.assets
        for citation in item.asset.citations
    )


def _details(run: RunMetrics, kit: CampaignKit) -> list[BadClaim]:
    if run.bad_claim_details:
        return run.bad_claim_details
    parsed = [entry.partition(": ") for entry in run.bad_claims]
    return [
        BadClaim(quote=quote, verdict=verdict, cited=_cited_in(quote, kit))
        for verdict, _, quote in parsed
    ]


def _unaudited(run: RunMetrics) -> bool:
    """A baseline whose audit never billed anything was never actually audited."""
    return run.mode == "baseline" and run.status == "ok" and run.assets and not run.audit_cost_usd


def rescore(
    results: EvalResults,
    briefs: list[AdversarialBrief],
    root: Path,
    examples_dir: Path,
    deps: EvalDeps,
    cap_usd: float,
) -> EvalResults:
    """Classify every rejected claim with the checker and recheck forbidden phrases."""
    by_id = {brief.id: brief for brief in briefs}
    budget = EvalBudget(cap_usd)
    runs: list[RunMetrics] = []
    stopped = results.stopped_reason
    for run in results.runs:
        kit = run_kit(run, root) if run.status != "failed" else None
        if kit is not None:
            brief, inputs = by_id[run.brief_id], apply_brief(by_id[run.brief_id], examples_dir)
            texts = shipped_text(kit)
            run = run.model_copy(
                update={
                    "bad_claim_details": _details(run, kit),
                    "forbidden_hits": brief.violations(texts),
                    "forbidden_contexts": brief.violation_contexts(texts),
                }
            )
            if _unaudited(run):
                run = run.model_copy(update={"status": "unaudited", "failure": UNAUDITED})
            try:
                run = classify(run, inputs, deps, budget)
            except EvalStopped as exc:
                stopped = f"Re-scoring stopped: {exc}"
        runs.append(run)
    return results.model_copy(
        update={
            "runs": runs,
            "spent_usd": results.spent_usd + budget.spent_usd,
            "stopped_reason": stopped,
        }
    )
