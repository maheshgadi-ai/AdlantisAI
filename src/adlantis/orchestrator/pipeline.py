"""Runs the agent team: research, strategy, concurrent copy, review, and design."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, TypeVar

from adlantis.agents.strategist import StrategyError
from adlantis.llm.budget import BudgetCap, BudgetExceeded
from adlantis.llm.images import ImageGenerator
from adlantis.llm.types import LLMError
from adlantis.orchestrator.image_stage import generate_images
from adlantis.orchestrator.policy import DEFAULT_POLICIES, AgentPolicy, call_with_policy
from adlantis.orchestrator.review_stage import build_review_loop
from adlantis.orchestrator.run_log import RunLog, record_research_issues
from adlantis.orchestrator.section_review import (
    SectionFailure,
    apply_image_review,
    image_sections,
    rebuild_strategy,
    strategy_sections,
)
from adlantis.orchestrator.team import AgentTeam
from adlantis.rules.copy_assets import variant_gaps
from adlantis.schemas.channels import Channel
from adlantis.schemas.copy import CampaignAsset, CopyRequest
from adlantis.schemas.design import DesignRequest, DesignResult, GeneratedImage
from adlantis.schemas.inputs import CampaignInputs
from adlantis.schemas.ledger import IssueLedger
from adlantis.schemas.research import ResearchBrief, ResearchResult
from adlantis.schemas.review import AssetGap, ReviewedAsset, ReviewOutcome
from adlantis.schemas.strategy import CampaignStrategy, StrategyRequest, StrategyResult

OutputT = TypeVar("OutputT")
RESEARCH_FAILED = (
    "Market research could not be completed, so the campaign relies on approved facts."
)
RESEARCH_SKIPPED = "Market research was skipped because the budget could not cover it."


class PipelineError(RuntimeError):
    """The run cannot produce a kit."""


@dataclass(frozen=True)
class PipelineOptions:
    """How one run behaves."""

    today: date
    concurrency: int = 4
    max_rounds: int = 2
    enable_images: bool = False
    search_hold_usd: float = 0.0
    search_usd_each: float = 0.0
    policies: dict[str, AgentPolicy] = field(default_factory=lambda: dict(DEFAULT_POLICIES))


@dataclass(frozen=True)
class PipelineResult:
    """Everything the packager needs from a finished run."""

    research: ResearchResult
    strategy: CampaignStrategy
    review: ReviewOutcome
    design: DesignResult
    images: list[GeneratedImage]
    channel_gaps: list[AssetGap]
    section_gaps: list[AssetGap] = field(default_factory=list)
    sections: list[ReviewedAsset] = field(default_factory=list)


class CampaignPipeline:
    """Coordinates one campaign. Independent work runs at the same time."""

    def __init__(
        self,
        inputs: CampaignInputs,
        team: AgentTeam,
        log: RunLog,
        options: PipelineOptions,
        *,
        budget: BudgetCap | None = None,
        images: ImageGenerator | None = None,
        run_dir: Path | None = None,
    ) -> None:
        self.inputs = inputs
        self.team = team
        self.log = log
        self.options = options
        self.budget = budget
        self.images = images
        self.run_dir = run_dir
        self._slots = asyncio.Semaphore(max(1, options.concurrency))
        self.ledger = IssueLedger()

    async def run(self) -> PipelineResult:
        """Run every stage.

        Raises:
            PipelineError: If no strategy or no copy could be produced.
        """
        research = await self._research()
        drafted = await self._strategy(research)
        strategy, strategy_checks, section_gaps = await self._verify_strategy(drafted, research)
        assets, channel_gaps = await self._copy(research, strategy)
        review = await self._review(assets, research)
        design = await self._design(review, strategy)
        design, image_checks = await self._verify_images(design, research)
        images = await generate_images(
            design.prompts,
            self.inputs,
            self.images if self.options.enable_images else None,
            self.run_dir,
            self.log,
            self._slots,
        )
        return PipelineResult(
            research,
            strategy,
            review,
            design,
            images,
            channel_gaps,
            section_gaps,
            [*strategy_checks, *image_checks],
        )

    async def _call(self, role: str, work: Callable[[Any], OutputT], data: Any) -> OutputT:
        policy = self.options.policies.get(role, AgentPolicy())
        async with self._slots:
            return await asyncio.to_thread(call_with_policy, work, data, policy, role)

    async def _research(self) -> ResearchResult:
        self.log.record("research", "started")
        hold = self.options.search_hold_usd
        if self.budget is not None:
            try:
                self.budget.reserve(hold)
            except BudgetExceeded as exc:
                self.log.record("research", "skipped", str(exc))
                return ResearchResult(gaps=[RESEARCH_SKIPPED])
        try:
            brief = ResearchBrief.from_campaign(self.inputs)
            research = await self._call("researcher", self.team.researcher.run, brief)
            billed = research.stats.searches * self.options.search_usd_each
            self.log.record("research", "finished", f"{len(research.findings)} findings")
            record_research_issues(self.log, research)
        except LLMError as exc:
            research, billed = ResearchResult(gaps=[RESEARCH_FAILED]), hold
            self.log.record("research", "failed", str(exc))
        if self.budget is not None:
            self.budget.charge(billed)
            self.budget.release(hold)
        return research

    async def _strategy(self, research: ResearchResult) -> StrategyResult:
        self.log.record("strategy", "started")
        request = StrategyRequest(
            brand=self.inputs.brand,
            product=self.inputs.product,
            facts=self.inputs.facts,
            findings=research.findings,
            today=self.options.today,
        )
        try:
            result = await self._call("strategist", self.team.strategist.run, request)
        except (LLMError, StrategyError) as exc:
            self.log.record("strategy", "failed", str(exc))
            raise PipelineError(f"No strategy could be produced: {exc}") from exc
        self.log.record("strategy", "finished", f"{len(result.strategy.key_messages)} messages")
        return result

    async def _write_channel(
        self, channel: Channel, research: ResearchResult, strategy: CampaignStrategy
    ) -> tuple[list[CampaignAsset], list[AssetGap]]:
        stage = f"copy:{channel}"
        self.log.record(stage, "started")
        request = CopyRequest(
            brand=self.inputs.brand,
            product=self.inputs.product,
            strategy=strategy,
            facts=self.inputs.facts,
            findings=research.findings,
            channel=channel,
            today=self.options.today,
        )
        try:
            written = await self._call("copywriter", self.team.copywriter.run, request)
        except LLMError as exc:
            self.log.record(stage, "failed", str(exc))
            reason = f"Copy for this channel could not be written: {exc}"
            return [], [AssetGap(asset_id=f"{channel}-all", channel=channel, reason=reason)]
        gaps = variant_gaps(channel, written.rejected)
        self.log.record(stage, "finished", f"{len(written.assets)} assets, {len(gaps)} dropped")
        for gap in gaps:
            self.log.record(stage, "skipped", f"{gap.asset_id}: {gap.reason}")
        return written.assets, gaps

    async def _copy(
        self, research: ResearchResult, strategy: CampaignStrategy
    ) -> tuple[list[CampaignAsset], list[AssetGap]]:
        written = await asyncio.gather(
            *(
                self._write_channel(channel, research, strategy)
                for channel in self.inputs.product.channels
            )
        )
        assets = [asset for channel_assets, _ in written for asset in channel_assets]
        gaps = [gap for _, channel_gaps in written for gap in channel_gaps]
        if not assets:
            raise PipelineError("No channel produced usable copy.")
        return assets, gaps

    async def _run_checks(
        self, assets: list[CampaignAsset], research: ResearchResult, max_rounds: int
    ) -> ReviewOutcome:
        loop = build_review_loop(
            self.inputs,
            self.team,
            research,
            today=self.options.today,
            policies=self.options.policies,
            concurrency=self.options.concurrency,
            max_rounds=max_rounds,
        )
        return await asyncio.to_thread(loop.review, assets, self.ledger)

    async def _review(self, assets: list[CampaignAsset], research: ResearchResult) -> ReviewOutcome:
        self.log.record("review", "started", f"{len(assets)} assets")
        outcome = await self._run_checks(assets, research, self.options.max_rounds)
        detail = f"{len(outcome.assets)} shipped, {len(outcome.gaps)} gaps"
        self.log.record("review", "finished", detail)
        return outcome

    async def _verify_strategy(
        self, drafted: StrategyResult, research: ResearchResult
    ) -> tuple[CampaignStrategy, list[ReviewedAsset], list[AssetGap]]:
        """Check every strategy statement before any copy is written from it."""
        self.log.record("verify:strategy", "started")
        usable = research.evidence.usable_ids()
        facts, today = self.inputs.facts, self.options.today
        sections = strategy_sections(drafted.strategy, facts, today, usable)
        outcome = await self._run_checks(sections, research, self.options.max_rounds)
        try:
            strategy, gaps = rebuild_strategy(drafted.strategy, outcome)
        except SectionFailure as exc:
            self.log.record("verify:strategy", "failed", str(exc))
            raise PipelineError(f"The strategy could not be verified: {exc}") from exc
        gaps += [
            AssetGap(
                asset_id=f"strategy-rejected-{number}",
                channel="strategy",
                reason="A key message was removed because it cited an unusable source.",
            )
            for number, _ in enumerate(drafted.rejected_messages, 1)
        ]
        for gap in gaps:
            self.log.record("verify:strategy", "skipped", f"{gap.asset_id}: {gap.reason}")
        detail = f"{len(outcome.assets)} statements passed, {len(gaps)} removed"
        self.log.record("verify:strategy", "finished", detail)
        return strategy, outcome.assets, gaps

    async def _verify_images(
        self, design: DesignResult, research: ResearchResult
    ) -> tuple[DesignResult, list[ReviewedAsset]]:
        """Check each image prompt. A prompt that fails is dropped, never rewritten."""
        if not design.prompts:
            return design, []
        self.log.record("verify:images", "started", f"{len(design.prompts)} prompts")
        usable = research.evidence.usable_ids()
        sections = image_sections(design, self.inputs.facts, self.options.today, usable)
        outcome = await self._run_checks(sections, research, max_rounds=0)
        checked = apply_image_review(design, outcome)
        detail = f"{len(checked.prompts)} passed, {len(outcome.gaps)} removed"
        self.log.record("verify:images", "finished", detail)
        return checked, outcome.assets

    async def _design(self, review: ReviewOutcome, strategy: CampaignStrategy) -> DesignResult:
        self.log.record("design", "started")
        request = DesignRequest(
            brand=self.inputs.brand,
            product=self.inputs.product,
            strategy=strategy,
            assets=[item.asset for item in review.assets],
        )
        try:
            design = await self._call("designer", self.team.designer.run, request)
        except LLMError as exc:  # images are optional, so the campaign continues without them
            self.log.record("design", "failed", str(exc))
            return DesignResult()
        self.log.record("design", "finished", f"{len(design.prompts)} prompts")
        return design
