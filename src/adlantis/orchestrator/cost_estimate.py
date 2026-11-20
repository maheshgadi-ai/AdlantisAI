"""Cost estimates shown before any billed run."""

from __future__ import annotations

from pydantic import BaseModel

from adlantis.config.models import ModelsConfig
from adlantis.config.settings import Settings
from adlantis.schemas.channels import Channel
from adlantis.schemas.copy import ASSET_VARIANTS
from adlantis.schemas.research import ResearchLimits

CHARS_PER_TOKEN = 4
PROMPT_TOKENS = 1500
SEARCH_SNIPPET_CHARS = 1500
RECORD_OVERHEAD_TOKENS = 60
TYPICAL_TURN_OUTPUT_TOKENS = 700
TAVILY_USD_PER_CREDIT = 0.008  # pay-as-you-go; https://docs.tavily.com/documentation/api-credits


class ResearchCostEstimate(BaseModel):
    """What one research run can cost, in USD."""

    model: str
    search_credits: int
    search_usd: float
    typical_model_usd: float
    worst_case_model_usd: float

    @property
    def typical_usd(self) -> float:
        """Expected total, with every search billed."""
        return self.typical_model_usd + self.search_usd

    @property
    def worst_case_usd(self) -> float:
        """Upper bound: every budget fully used and nothing served from a prompt cache."""
        return self.worst_case_model_usd + self.search_usd


def estimate_research_cost(
    models: ModelsConfig, settings: Settings, limits: ResearchLimits | None = None
) -> ResearchCostEstimate:
    """Estimate one research run from the configured model's prices and the run's hard limits."""
    limits = limits or ResearchLimits()
    spec = models.resolve("researcher", settings)
    price = models.price_for(spec.model)
    results = limits.max_searches * limits.results_per_search
    web_chars = results * SEARCH_SNIPPET_CHARS + limits.max_fetches * limits.fetch_chars
    records = results + limits.max_fetches
    context = PROMPT_TOKENS + web_chars // CHARS_PER_TOKEN + records * RECORD_OVERHEAD_TOKENS
    calls = limits.max_turns + 1
    worst_output = limits.max_turns * limits.turn_output_tokens + limits.final_output_tokens
    typical_output = calls * TYPICAL_TURN_OUTPUT_TOKENS
    return ResearchCostEstimate(
        model=spec.label,
        search_credits=limits.max_searches,
        search_usd=limits.max_searches * TAVILY_USD_PER_CREDIT,
        typical_model_usd=_usd(calls * context // 2, typical_output, price),
        worst_case_model_usd=_usd(calls * context, worst_output, price),
    )


def token_cost(input_tokens: int, output_tokens: int, price) -> float:
    """The price of one call with these token counts, in USD."""
    return _usd(input_tokens, output_tokens, price)


def _usd(input_tokens: int, output_tokens: int, price) -> float:
    return (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / 1_000_000


# Tokens per call: (input, typical output, largest expected output).
_CAMPAIGN_CALLS = {
    "strategist": (6000, 1500, 4000),
    "copywriter": (7000, 1500, 4000),
    "revision": (6000, 500, 2000),
    "claim_checker": (3000, 1200, 4000),
    "designer": (3000, 1000, 3000),
    "section_check": (3000, 500, 2000),
}
_STRATEGY_SECTIONS = 10  # positioning, concept, and about eight key messages
_BASELINE_CALL = (8000, 4000, 16000)


class CampaignCostEstimate(BaseModel):
    """What strategy, copy, and claim review can cost for one campaign, in USD."""

    assets: int
    typical_usd: float
    worst_case_usd: float


def estimate_campaign_cost(
    models: ModelsConfig, settings: Settings, channels: list[Channel], max_rounds: int = 2
) -> CampaignCostEstimate:
    """Estimate one campaign. The worst case revises every asset for every allowed round."""
    assets = sum(ASSET_VARIANTS[channel] for channel in channels)
    worst_counts = {
        "strategist": 1,
        "copywriter": len(channels),
        "revision": assets * max_rounds,
        "claim_checker": assets * (max_rounds + 1),
        "designer": 1,
        "section_check": _STRATEGY_SECTIONS + len(channels) + assets,
    }
    typical_counts = worst_counts | {"revision": assets // 2, "claim_checker": assets + assets // 2}
    return CampaignCostEstimate(
        assets=assets,
        typical_usd=_campaign_usd(models, settings, typical_counts, 1),
        worst_case_usd=_campaign_usd(models, settings, worst_counts, 2),
    )


def estimate_baseline_cost(models: ModelsConfig, settings: Settings) -> CampaignCostEstimate:
    """Estimate the single-prompt baseline, which makes one call on the copywriter's model."""
    price = models.price_for(models.resolve("copywriter", settings).model)
    input_tokens, typical, largest = _BASELINE_CALL
    return CampaignCostEstimate(
        assets=0,
        typical_usd=_usd(input_tokens, typical, price),
        worst_case_usd=_usd(input_tokens, largest, price),
    )


def _campaign_usd(
    models: ModelsConfig, settings: Settings, counts: dict[str, int], output_column: int
) -> float:
    total = 0.0
    for call, count in counts.items():
        role = {"revision": "copywriter", "section_check": "claim_checker"}.get(call, call)
        price = models.price_for(models.resolve(role, settings).model)
        tokens = _CAMPAIGN_CALLS[call]
        total += count * _usd(tokens[0], tokens[output_column], price)
    return total
