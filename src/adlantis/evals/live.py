"""Connects the evaluation harness to the real pipeline. Only `adlantis eval run` uses this."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from adlantis.agents import ClaimChecker
from adlantis.agents.claim_triage import ClaimTriage
from adlantis.agents.judge import Judge
from adlantis.config import Settings
from adlantis.evals.briefs import AdversarialBrief
from adlantis.evals.claim_labels import LabeledSnippet, load_claim_labels
from adlantis.evals.claim_severity import BadClaim, ClassifiedClaim, settle_triage
from adlantis.evals.fixture_web import fixture_registry
from adlantis.evals.harness import EvalDeps, RunOutcome
from adlantis.evals.pairwise import PairResult, compare
from adlantis.evals.recall import RecallReport, score_recall
from adlantis.llm import LLMError, ModelRouter
from adlantis.orchestrator.run_log import QUARANTINE_STAGE, redact
from adlantis.orchestrator.runner import RunDependencies, RunFailed, RunRequest, start_run
from adlantis.rules.channels import load_channel_limits
from adlantis.rules.context import RuleContext
from adlantis.schemas.claim_check import ClaimCheckResult
from adlantis.schemas.copy import CampaignAsset
from adlantis.schemas.evidence_store import EvidenceStore
from adlantis.schemas.inputs import CampaignInputs, load_campaign_inputs
from adlantis.schemas.kit import CampaignKit
from adlantis.schemas.triage import TriageRequest

_RECALL_WORKERS = 4


def _spent_in_log(run_dir: Path) -> float:
    lines = (run_dir / "run_log.jsonl").read_text(encoding="utf-8").splitlines()
    return float(json.loads(lines[-1])["spent_usd"]) if lines else 0.0


def _withheld(run_dir: Path) -> tuple[str, ...]:
    rows = (json.loads(line) for line in (run_dir / "run_log.jsonl").read_text().splitlines())
    return tuple(row["detail"] for row in rows if row["stage"] == QUARANTINE_STAGE)


def live_deps(settings: Settings, outputs_dir: Path, examples_dir: Path, today: date) -> EvalDeps:
    """The real, billed steps. Outputs stay in the scratch folder given."""
    settings = settings.model_copy(update={"enable_images": False})

    def router(profile: str, cap: float) -> ModelRouter:
        return ModelRouter.from_settings(settings, profile=profile, max_cost_usd=cap)

    def run(
        brief: AdversarialBrief, inputs: CampaignInputs, profile: str, baseline: bool, cap: float
    ) -> RunOutcome:
        request = RunRequest(
            inputs=inputs,
            max_cost_usd=cap,
            profile=profile,
            baseline=baseline,
            outputs_dir=outputs_dir / brief.id,
        )
        deps = RunDependencies(make_tools=lambda _settings, _tracer: fixture_registry(brief))
        started = time.perf_counter()
        try:
            output = start_run(request, settings, deps)
        except RunFailed as exc:
            return RunOutcome(
                None,
                _spent_in_log(exc.run_dir),
                time.perf_counter() - started,
                error=redact(str(exc)),
                run_dir=str(exc.run_dir),
            )
        elapsed = time.perf_counter() - started
        return RunOutcome(
            output.kit,
            output.kit.cost.model_usd,
            elapsed,
            _withheld(output.run_dir),
            run_dir=str(output.run_dir),
        )

    def audit(
        kit: CampaignKit, inputs: CampaignInputs, profile: str, cap: float
    ) -> tuple[list[ClaimCheckResult], float, list[str]]:
        built = router(profile, cap)
        ctx = RuleContext(
            brand=inputs.brand, facts=inputs.facts, today=today, product_names=inputs.product.names
        )
        checker = ClaimChecker(built, ctx, EvidenceStore())
        results: list[ClaimCheckResult] = []
        errors: list[str] = []
        for item in kit.assets:
            try:
                results.append(checker.run(item.asset))
            except LLMError as exc:
                errors.append(f"{item.asset.asset_id}: {redact(str(exc), 200)}")
        return results, built.usage.cost_usd, errors

    def judge(
        team: CampaignKit,
        baseline: CampaignKit,
        inputs: CampaignInputs,
        profile: str,
        repeat: int,
        brief_id: str,
        cap: float,
    ) -> PairResult:
        built = router(profile, cap)
        common = {"brief_id": brief_id, "profile": profile, "repeat": repeat}
        try:
            pair = compare(team, baseline, inputs, Judge(built).run, **common)
        except LLMError as exc:
            pair = PairResult(outcome="no_comparison", error=redact(str(exc)), **common)
        return pair.model_copy(update={"cost_usd": built.usage.cost_usd})

    def recall(profile: str, cap: float) -> tuple[RecallReport, float]:
        built = router(profile, cap)
        checkers = {
            name: ClaimChecker(built, _recall_context(name, examples_dir, today), EvidenceStore())
            for name in ("tamsin-hollow-roasters", "kestrune-cycles")
        }

        def extract(snippet: LabeledSnippet):
            field = next(iter(load_channel_limits().channels[snippet.channel]))
            asset = CampaignAsset(
                asset_id=snippet.id, channel=snippet.channel, fields={field: snippet.text}
            )
            return checkers[snippet.brand].run(asset).claims

        snippets = load_claim_labels().snippets
        with ThreadPoolExecutor(max_workers=_RECALL_WORKERS) as pool:
            attempts = list(pool.map(lambda s: _attempt(extract, s), snippets))
        done = {s.id: result for s, result in zip(snippets, attempts, strict=True)}
        report = score_recall(snippets, lambda snippet: _unwrap(done[snippet.id]))
        return report, built.usage.cost_usd

    def triage(
        inputs: CampaignInputs, claims: list[BadClaim], profile: str, cap: float
    ) -> tuple[list[ClassifiedClaim], float, str | None]:
        built = router(profile, cap)
        request = TriageRequest(
            brand=inputs.brand,
            product=inputs.product,
            facts=inputs.facts,
            today=today,
            claims=[claim.quote for claim in claims],
        )
        try:
            draft = ClaimTriage(built).run(request)
        except LLMError as exc:
            settled = settle_triage(claims, [], inputs, today)
            return settled, built.usage.cost_usd, redact(str(exc))
        return settle_triage(claims, draft.items, inputs, today), built.usage.cost_usd, None

    return EvalDeps(run=run, audit=audit, judge=judge, recall=recall, triage=triage)


def _attempt(extract, snippet: LabeledSnippet):
    try:
        return extract(snippet)
    except LLMError as exc:
        return exc


def _unwrap(result):
    if isinstance(result, Exception):
        raise result
    return result


def _recall_context(brand: str, examples_dir: Path, today: date) -> RuleContext:
    folder = examples_dir / brand
    inputs = load_campaign_inputs(
        folder / "brand.yaml", folder / "facts.yaml", folder / "product.yaml"
    )
    return RuleContext(brand=inputs.brand, facts=inputs.facts, today=today)
