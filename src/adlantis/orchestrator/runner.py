"""Starts a run from start to finish: budget, agents, run log, kit, and outputs folder."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from adlantis.agents.baseline import BaselineAgent
from adlantis.config import Settings, load_profile
from adlantis.config.images import load_image_config
from adlantis.llm.router import ModelRouter
from adlantis.llm.types import LLMError
from adlantis.observability.tracing import Tracer, build_tracer
from adlantis.orchestrator.cost_estimate import (
    TAVILY_USD_PER_CREDIT,
    estimate_baseline_cost,
    estimate_campaign_cost,
    estimate_research_cost,
)
from adlantis.orchestrator.kit_builder import (
    KitBlocked,
    KitParts,
    build_baseline_kit,
    build_team_kit,
)
from adlantis.orchestrator.kit_store import write_kit
from adlantis.orchestrator.pipeline import CampaignPipeline, PipelineError, PipelineOptions
from adlantis.orchestrator.policy import DEFAULT_POLICIES, call_with_policy
from adlantis.orchestrator.run_log import RunEvent, RunLog, utc_now
from adlantis.orchestrator.team import AgentTeam, build_team
from adlantis.rules.context import RuleContext
from adlantis.rules.engine import check_asset
from adlantis.schemas.baseline import BaselineRequest
from adlantis.schemas.copy import ASSET_VARIANTS
from adlantis.schemas.design import TEXT_ONLY_CHANNELS
from adlantis.schemas.inputs import CampaignInputs
from adlantis.schemas.kit import CampaignKit, KitCost
from adlantis.schemas.research import ResearchLimits
from adlantis.schemas.review import ReviewedAsset
from adlantis.tools.registry import ToolRegistry, build_default_registry


class RunFailed(RuntimeError):
    """A run stopped without a kit. Its run log explains why."""

    def __init__(self, message: str, run_dir: Path) -> None:
        super().__init__(message)
        self.run_dir = run_dir


@dataclass(frozen=True)
class RunRequest:
    """What to run and how much it may spend."""

    inputs: CampaignInputs
    max_cost_usd: float
    profile: str = "budget"
    baseline: bool = False
    outputs_dir: Path = Path("outputs")
    concurrency: int = 4


@dataclass(frozen=True)
class RunEstimate:
    """What a run is expected to cost, in USD."""

    typical_usd: float
    worst_case_usd: float


@dataclass(frozen=True)
class RunOutput:
    """A finished run."""

    run_dir: Path
    kit: CampaignKit


@dataclass(frozen=True)
class RunDependencies:
    """What a run builds on. Tests replace these with fakes."""

    clock: Callable[[], datetime] = utc_now
    make_router: Callable[[RunRequest, Settings, Tracer], ModelRouter] | None = None
    make_tools: Callable[[Settings, Tracer], ToolRegistry] | None = None
    make_team: Callable[[ModelRouter, ToolRegistry, ResearchLimits], AgentTeam] = field(
        default=build_team
    )
    on_event: Callable[[RunEvent], None] | None = None


def estimate_run(request: RunRequest, settings: Settings) -> RunEstimate:
    """The cost estimate shown before a run starts."""
    models = load_profile(request.profile)
    if request.baseline:
        baseline = estimate_baseline_cost(models, settings)
        return RunEstimate(baseline.typical_usd, baseline.worst_case_usd)
    channels = request.inputs.product.channels
    research = estimate_research_cost(models, settings)
    campaign = estimate_campaign_cost(models, settings, channels)
    images = 0.0
    if settings.enable_images:
        pictured = sum(ASSET_VARIANTS[c] for c in channels if c not in TEXT_ONLY_CHANNELS)
        images = pictured * load_image_config().reserve_usd_per_image
    return RunEstimate(
        research.typical_usd + campaign.typical_usd + images,
        research.worst_case_usd + campaign.worst_case_usd + images,
    )


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "campaign"


def _new_run_dir(request: RunRequest, started: datetime) -> Path:
    stem = f"{started:%Y%m%d-%H%M%S}-{_slug(request.inputs.brand.name)}"
    run_dir, number = request.outputs_dir / stem, 1
    while run_dir.exists():
        number += 1
        run_dir = request.outputs_dir / f"{stem}-{number}"
    run_dir.mkdir(parents=True)
    return run_dir


def _cost(router: ModelRouter, request: RunRequest) -> KitCost:
    other = router.budget.other_usd if router.budget else 0.0
    model = router.usage.cost_usd
    return KitCost(
        total_usd=round(model + other, 6),
        model_usd=round(model, 6),
        other_usd=round(other, 6),
        cap_usd=request.max_cost_usd,
        by_role={role: round(u.cost_usd, 6) for role, u in router.usage.by_role.items()},
    )


def _run_team(
    request: RunRequest,
    settings: Settings,
    router: ModelRouter,
    tools: ToolRegistry,
    log: RunLog,
    run_dir: Path,
    started: datetime,
    make_team: Callable[[ModelRouter, ToolRegistry, ResearchLimits], AgentTeam],
) -> CampaignKit:
    limits = ResearchLimits()
    estimate = estimate_research_cost(router.models, settings, limits)
    limits = limits.model_copy(update={"max_cost_usd": estimate.worst_case_model_usd})
    options = PipelineOptions(
        today=started.date(),
        concurrency=request.concurrency,
        enable_images=settings.enable_images,
        search_hold_usd=limits.max_searches * TAVILY_USD_PER_CREDIT,
        search_usd_each=TAVILY_USD_PER_CREDIT,
    )
    images = router.image_generator() if settings.enable_images else None
    pipeline = CampaignPipeline(
        request.inputs,
        make_team(router, tools, limits),
        log,
        options,
        budget=router.budget,
        images=images,
        run_dir=run_dir,
    )
    result = asyncio.run(pipeline.run())
    return build_team_kit(
        KitParts(
            run_id=run_dir.name,
            created_at=started,
            profile=request.profile,
            inputs=request.inputs,
            strategy=result.strategy,
            review=result.review,
            evidence=result.research.evidence,
            cost=_cost(router, request),
            research_gaps=result.research.gaps,
            design=result.design,
            images=result.images,
            extra_gaps=[*result.channel_gaps, *result.section_gaps],
            sections=result.sections,
        )
    )


def _run_baseline(
    request: RunRequest, router: ModelRouter, log: RunLog, run_dir: Path, started: datetime
) -> CampaignKit:
    inputs, today = request.inputs, started.date()
    log.record("baseline", "started")
    data = BaselineRequest(
        brand=inputs.brand, product=inputs.product, facts=inputs.facts, today=today
    )
    try:
        result = call_with_policy(
            BaselineAgent(router).run, data, DEFAULT_POLICIES["baseline"], "baseline"
        )
    except LLMError as exc:
        log.record("baseline", "failed", str(exc))
        raise PipelineError(f"The baseline could not be produced: {exc}") from exc
    log.record("baseline", "finished", f"{len(result.assets)} assets, {len(result.gaps)} dropped")
    for gap in result.gaps:
        log.record(f"copy:{gap.channel}", "skipped", f"{gap.asset_id}: {gap.reason}")
    ctx = RuleContext(
        brand=inputs.brand, facts=inputs.facts, today=today, product_names=inputs.product.names
    )
    assets = [
        ReviewedAsset(asset=asset, warnings=check_asset(asset, ctx).violations)
        for asset in result.assets
    ]
    return build_baseline_kit(
        run_id=run_dir.name,
        created_at=started,
        profile=request.profile,
        inputs=inputs,
        summary=f"{result.positioning} {result.concept}".strip(),
        assets=assets,
        cost=_cost(router, request),
        gaps=result.gaps,
    )


def start_run(
    request: RunRequest, settings: Settings, deps: RunDependencies | None = None
) -> RunOutput:
    """Run a campaign or baseline and save its kit as a draft.

    Raises:
        RunFailed: If the run stopped before a kit could be built.
    """
    deps = deps or RunDependencies()
    started = deps.clock()
    run_dir = _new_run_dir(request, started)
    tracer = build_tracer(settings)
    make_router = deps.make_router or (
        lambda req, conf, trace: ModelRouter.from_settings(
            conf, profile=req.profile, tracer=trace, max_cost_usd=req.max_cost_usd
        )
    )
    router = make_router(request, settings, tracer)
    log = RunLog(
        run_dir / "run_log.jsonl",
        clock=deps.clock,
        spent=lambda: router.budget.spent_usd if router.budget else router.usage.cost_usd,
        on_event=deps.on_event,
    )
    make_tools = deps.make_tools or (lambda conf, trace: build_default_registry(conf, tracer=trace))
    log.record("run", "started", "baseline" if request.baseline else "team")
    try:
        with make_tools(settings, tracer) as tools:
            kit = (
                _run_baseline(request, router, log, run_dir, started)
                if request.baseline
                else _run_team(
                    request, settings, router, tools, log, run_dir, started, deps.make_team
                )
            )
        write_kit(kit, run_dir)
    except (PipelineError, KitBlocked) as exc:
        log.record("run", "failed", str(exc))
        raise RunFailed(str(exc), run_dir) from exc
    finally:
        tracer.flush()
    log.record("run", "finished", f"{len(kit.assets)} assets, {len(kit.gaps)} gaps")
    return RunOutput(run_dir, kit)
