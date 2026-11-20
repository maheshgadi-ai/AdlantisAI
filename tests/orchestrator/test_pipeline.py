"""The pipeline runs independent work at once and keeps failures contained."""

import asyncio
import threading

import pytest

from adlantis.agents.strategist import StrategyError
from adlantis.llm import LLMError
from adlantis.llm.budget import BudgetCap
from adlantis.llm.images import ImageResult
from adlantis.orchestrator.pipeline import (
    RESEARCH_FAILED,
    RESEARCH_SKIPPED,
    CampaignPipeline,
    PipelineError,
    PipelineOptions,
)
from adlantis.orchestrator.policy import AgentPolicy
from adlantis.orchestrator.review_loop import ReviewContext, ReviewLoop
from adlantis.orchestrator.run_log import RunLog
from adlantis.rules.image_prompts import with_safety_suffix
from adlantis.schemas.channels import SECTION_CHANNELS
from tests.orchestrator.kit_helpers import (
    INPUTS,
    TODAY,
    StubChecker,
    StubCopywriter,
    StubDesigner,
    StubResearcher,
    StubStrategist,
    make_asset,
    stub_team,
)
from tests.rules.helpers import SHEET, brand

NO_RETRY = dict.fromkeys(
    ("researcher", "strategist", "copywriter", "claim_checker", "designer"),
    AgentPolicy(timeout_seconds=10, retries=0),
)
CHANNELS = ["search_ad", "instagram", "email", "landing_page"]


class Generator:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.prompts: list[str] = []

    def generate(self, prompt: str, _size: str) -> ImageResult:
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return ImageResult(b"png", "image-model", 0.02)


def pipeline(team=None, budget=None, images=None, run_dir=None, **options):
    log = RunLog()
    values = {"today": TODAY, "policies": NO_RETRY, **options}
    built = CampaignPipeline(
        INPUTS,
        team or stub_team(),
        log,
        PipelineOptions(**values),
        budget=budget,
        images=images,
        run_dir=run_dir,
    )
    return built, log


def run(*args, **kwargs):
    built, log = pipeline(*args, **kwargs)
    return asyncio.run(built.run()), log


def statuses(log, stage: str) -> list[str]:
    return [event.status for event in log.events if event.stage == stage]


def test_full_run_ships_every_channel() -> None:
    result, log = run()
    assert [item.asset.channel for item in result.review.assets] == CHANNELS
    assert result.channel_gaps == []
    assert statuses(log, "review") == ["started", "finished"]


def test_stages_run_in_order() -> None:
    _, log = run()
    stages = [e.stage.split(":")[0] for e in log.events if e.status == "started"]
    assert stages.index("research") < stages.index("strategy") < stages.index("copy")
    assert stages.index("copy") < stages.index("review") < stages.index("design")


def test_channels_are_written_at_the_same_time() -> None:
    barrier = threading.Barrier(len(CHANNELS), timeout=5)
    result, _ = run(stub_team(copywriter=StubCopywriter(barrier=barrier)))
    assert len(result.review.assets) == len(CHANNELS)


def test_concurrency_limit_is_respected() -> None:
    barrier = threading.Barrier(len(CHANNELS), timeout=0.2)
    team = stub_team(copywriter=StubCopywriter(barrier=barrier))
    with pytest.raises(threading.BrokenBarrierError):
        run(team, concurrency=2)


def test_failed_channel_becomes_a_gap_and_the_rest_continue() -> None:
    result, log = run(stub_team(copywriter=StubCopywriter(failing={"email"})))
    assert [gap.asset_id for gap in result.channel_gaps] == ["email-all"]
    assert "email" not in {item.asset.channel for item in result.review.assets}
    assert statuses(log, "copy:email") == ["started", "failed"]


def test_channel_with_only_rejected_variants_becomes_a_gap() -> None:
    team = stub_team(copywriter=StubCopywriter(empty=True))
    with pytest.raises(PipelineError, match="No channel produced usable copy"):
        run(team)


def test_no_copy_at_all_stops_the_run() -> None:
    team = stub_team(copywriter=StubCopywriter(failing=set(CHANNELS)))
    with pytest.raises(PipelineError):
        run(team)


@pytest.mark.parametrize("error", [LLMError("down"), StrategyError("no usable message")])
def test_strategy_failure_stops_the_run(error: Exception) -> None:
    with pytest.raises(PipelineError, match="No strategy"):
        run(stub_team(strategist=StubStrategist(error)))


def test_research_failure_continues_and_is_reported() -> None:
    result, log = run(stub_team(researcher=StubResearcher(LLMError("down"))))
    assert result.research.gaps == [RESEARCH_FAILED]
    assert statuses(log, "research") == ["started", "failed"]


def test_unverifiable_asset_never_ships() -> None:
    team = stub_team(checker=StubChecker(failing={"email-1"}))
    result, _ = run(team)
    assert "email-1" not in {item.asset.asset_id for item in result.review.assets}
    assert [gap.asset_id for gap in result.review.gaps] == ["email-1"]


def test_design_failure_keeps_the_campaign() -> None:
    result, log = run(stub_team(designer=StubDesigner(LLMError("down"))))
    assert len(result.review.assets) == len(CHANNELS)
    assert statuses(log, "design") == ["started", "failed"]


def test_searches_are_charged_and_the_hold_released() -> None:
    budget = BudgetCap(1.0)
    run(budget=budget, search_hold_usd=0.032, search_usd_each=0.008)
    assert budget.other_usd == pytest.approx(0.032)
    assert budget._holds == 0


def test_only_searches_actually_made_are_charged() -> None:
    budget = BudgetCap(1.0)
    team = stub_team(researcher=StubResearcher(searches=2))
    run(team, budget=budget, search_hold_usd=0.032, search_usd_each=0.008)
    assert budget.other_usd == pytest.approx(0.016)


def test_failed_research_is_charged_the_full_hold() -> None:
    budget = BudgetCap(1.0)
    team = stub_team(researcher=StubResearcher(LLMError("down")))
    run(team, budget=budget, search_hold_usd=0.032, search_usd_each=0.008)
    assert budget.other_usd == pytest.approx(0.032)
    assert budget._holds == 0


def test_research_is_skipped_when_the_budget_cannot_cover_it() -> None:
    result, log = run(budget=BudgetCap(0.01), search_hold_usd=0.032)
    assert result.research.gaps == [RESEARCH_SKIPPED]
    assert statuses(log, "research") == ["started", "skipped"]


def test_images_are_never_generated_by_default(tmp_path) -> None:
    generator = Generator()
    result, log = run(images=generator, run_dir=tmp_path)
    assert (result.images, generator.prompts) == ([], [])
    assert statuses(log, "images") == ["skipped"]


def test_enabled_images_are_saved_and_labeled(tmp_path) -> None:
    result, _ = run(images=Generator(), run_dir=tmp_path, enable_images=True)
    image = result.images[0]
    assert image.label == "AI-generated image"
    assert (tmp_path / image.file).read_bytes() == b"png"
    assert len(result.images) == 3  # search ads are text only


def test_unsafe_stored_prompt_is_never_sent(tmp_path) -> None:
    generator = Generator()
    team = stub_team(designer=StubDesigner(prompt=with_safety_suffix("A cup with a logo.")))
    result, log = run(team, images=generator, run_dir=tmp_path, enable_images=True)
    assert (result.images, generator.prompts) == ([], [])
    assert "skipped" in statuses(log, "image:email-1")


def test_image_failure_keeps_the_campaign(tmp_path) -> None:
    result, log = run(images=Generator(LLMError("down")), run_dir=tmp_path, enable_images=True)
    assert result.images == [] and len(result.review.assets) == len(CHANNELS)
    assert "failed" in statuses(log, "image:email-1")


class BarrierChecker:
    def __init__(self, barrier: threading.Barrier) -> None:
        self.barrier = barrier

    def run(self, asset):
        if asset.channel not in SECTION_CHANNELS:
            self.barrier.wait()
        return StubChecker().run(asset)


def review_context() -> ReviewContext:
    return ReviewContext(
        brand=brand(), facts=SHEET, findings=[], today=TODAY, allowed_references=frozenset()
    )


def assets() -> list:
    return [make_asset(f"email-{n}") for n in range(1, 4)]


def test_review_checks_assets_at_the_same_time_and_keeps_their_order() -> None:
    loop = ReviewLoop(
        BarrierChecker(threading.Barrier(3, timeout=5)),
        StubCopywriter(),
        review_context(),
        concurrency=3,
    )
    outcome = loop.review(assets())
    assert [item.asset.asset_id for item in outcome.assets] == ["email-1", "email-2", "email-3"]


def test_pipeline_reviews_assets_at_the_same_time() -> None:
    checker = BarrierChecker(threading.Barrier(len(CHANNELS), timeout=5))
    result, _ = run(stub_team(checker=checker))
    assert len(result.review.assets) == len(CHANNELS)


def test_review_with_no_concurrency_setting_still_runs() -> None:
    loop = ReviewLoop(StubChecker(), StubCopywriter(), review_context(), concurrency=0)
    assert len(loop.review(assets()).assets) == 3


def test_review_is_sequential_by_default() -> None:
    loop = ReviewLoop(
        BarrierChecker(threading.Barrier(3, timeout=0.05)), StubCopywriter(), review_context()
    )
    with pytest.raises(threading.BrokenBarrierError):
        loop.review(assets())
