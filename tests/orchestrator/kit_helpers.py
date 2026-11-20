"""Fictional inputs and stand-in agents for pipeline and packaging tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from adlantis.orchestrator.kit_builder import KitParts, build_team_kit
from adlantis.orchestrator.section_review import image_sections, strategy_sections
from adlantis.orchestrator.team import AgentTeam
from adlantis.rules.image_prompts import with_safety_suffix
from adlantis.schemas import (
    CampaignAsset,
    CampaignStrategy,
    ChannelCopy,
    CheckedClaim,
    Citation,
    ClaimCheckResult,
    EvidenceStore,
    ResearchResult,
    ReviewedAsset,
    ReviewOutcome,
    RevisionPlan,
    SourceRating,
    StrategyResult,
    load_campaign_inputs,
)
from adlantis.schemas.design import DesignResult, ImagePrompt
from adlantis.schemas.kit import KitCost

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "tamsin-hollow-roasters"
INPUTS = load_campaign_inputs(
    EXAMPLE / "brand.yaml", EXAMPLE / "facts.yaml", EXAMPLE / "product.yaml"
)
TODAY = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
QUOTE = "Every bag is roasted within 48 hours of shipping."
STRATEGY = CampaignStrategy(
    positioning="Traceable coffee for home brewers.",
    concept="Know the bag.",
    key_messages=[{"message": QUOTE, "references": ["F-001"]}],
    channel_mix=[{"channel": "email", "role": "Launch", "rationale": "Reaches subscribers."}],
)
COST = KitCost(total_usd=0.2, model_usd=0.17, other_usd=0.03, cap_usd=1.0)


def make_asset(asset_id: str = "email-1", channel: str = "email") -> CampaignAsset:
    return CampaignAsset(
        asset_id=asset_id,
        channel=channel,
        fields={"body": QUOTE},
        citations=[Citation(text=QUOTE, references=["F-001"])],
        references=["F-001"],
    )


def make_claim(asset_id: str = "email-1", **changes: object) -> CheckedClaim:
    values = {
        "id": f"{asset_id}/C1",
        "asset_id": asset_id,
        "field": "body",
        "quote": QUOTE,
        "claim_type": "product_fact",
        "references": ["F-001"],
        "verdict": "supported",
        "supporting_passage": QUOTE,
        "reason": "The approved fact says so.",
        "decided_by": "model",
    }
    return CheckedClaim.model_validate({**values, **changes})


def reviewed(asset_id: str = "email-1", channel: str = "email", **claim: object) -> ReviewedAsset:
    asset = make_asset(asset_id, channel)
    return ReviewedAsset(asset=asset, claims=[make_claim(asset_id, **claim)])


def web_evidence(url: str = "https://publisher.example/report") -> EvidenceStore:
    store = EvidenceStore()
    rating = SourceRating(score=0.9, tier="high", label="news", rule="domain:publisher.example")
    store.add(url=url, title="Coffee report", excerpt=QUOTE, tool="web_search", rating=rating)
    return store


def verified_sections(strategy=STRATEGY, design: DesignResult | None = None) -> list:
    """Passing checks for every strategy statement and image prompt."""
    sections = strategy_sections(strategy, INPUTS.facts, TODAY)
    sections += image_sections(design or DesignResult(), INPUTS.facts, TODAY)
    return [ReviewedAsset(asset=section) for section in sections]


def parts(*assets: ReviewedAsset, **changes: object) -> KitParts:
    values = {
        "run_id": "20261118-120000-tamsin",
        "created_at": NOW,
        "profile": "budget",
        "inputs": INPUTS,
        "strategy": STRATEGY,
        "review": ReviewOutcome(assets=list(assets) or [reviewed()]),
        "evidence": EvidenceStore(),
        "cost": COST,
    }
    merged = {**values, **changes}
    merged.setdefault("sections", verified_sections(merged["strategy"], merged.get("design")))
    return KitParts(**merged)


def make_kit(*assets: ReviewedAsset, **changes: object):
    return build_team_kit(parts(*assets, **changes))


class StubResearcher:
    def __init__(self, error: Exception | None = None, searches: int = 4) -> None:
        self.error = error
        self.searches = searches

    def run(self, _brief) -> ResearchResult:
        if self.error:
            raise self.error
        result = ResearchResult(gaps=["No competitor data."])
        result.stats.searches = self.searches
        return result


class StubStrategist:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def run(self, _request) -> StrategyResult:
        if self.error:
            raise self.error
        return StrategyResult(strategy=STRATEGY)


class StubCopywriter:
    def __init__(self, failing: set[str] | None = None, barrier=None, empty: bool = False) -> None:
        self.failing = failing or set()
        self.barrier = barrier
        self.empty = empty

    def run(self, request) -> ChannelCopy:
        if self.barrier is not None:
            self.barrier.wait()
        if request.channel in self.failing:
            from adlantis.llm.types import LLMError

            raise LLMError("provider failed")
        if self.empty:
            return ChannelCopy(rejected=["Variant 1: has an empty field"])
        return ChannelCopy(assets=[make_asset(f"{request.channel}-1", request.channel)])

    def revise(self, _request) -> RevisionPlan:
        return RevisionPlan()


class StubChecker:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()

    def run(self, asset) -> ClaimCheckResult:
        if asset.asset_id in self.failing:
            from adlantis.llm.types import LLMError

            raise LLMError("checker failed")
        return ClaimCheckResult(asset_id=asset.asset_id, claims=[make_claim(asset.asset_id)])


class StubDesigner:
    def __init__(self, error: Exception | None = None, prompt: str | None = None) -> None:
        self.error = error
        self.prompt = prompt

    def run(self, request) -> DesignResult:
        if self.error:
            raise self.error
        text = self.prompt or with_safety_suffix("A quiet kitchen table at dawn.")
        return DesignResult(
            prompts=[
                ImagePrompt(
                    asset_id=asset.asset_id,
                    channel=asset.channel,
                    prompt=text,
                    alt_text="A kitchen table at dawn.",
                    size="1024x1024",
                )
                for asset in request.assets
                if asset.channel != "search_ad"
            ]
        )


def stub_team(**changes: object) -> AgentTeam:
    checker = changes.pop("checker", StubChecker())
    values = {
        "researcher": StubResearcher(),
        "strategist": StubStrategist(),
        "copywriter": StubCopywriter(),
        "designer": StubDesigner(),
        "make_checker": lambda _ctx, _evidence: checker,
    }
    return AgentTeam(**{**values, **changes})
