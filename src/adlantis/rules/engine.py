"""Run every rule over campaign copy. Code rules always win over model judgments."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator

from adlantis.rules import checks
from adlantis.rules.channel_checks import check_channel_limits
from adlantis.rules.context import RuleContext
from adlantis.schemas.assets import AssetCopy
from adlantis.schemas.rules import RuleId, RuleReport, RuleViolation

Check = Callable[[AssetCopy, RuleContext], Iterator[RuleViolation]]

RULES: dict[RuleId, Check] = {
    "banned_word": checks.check_banned_words,
    "banned_claim_type": checks.check_banned_claim_types,
    "health_claim": checks.check_health,
    "environmental_claim": checks.check_environmental,
    "superlative_claim": checks.check_superlatives,
    "pricing_claim": checks.check_pricing,
    "testimonial_claim": checks.check_testimonials,
    "competitor_disparagement": checks.check_competitors,
    "channel_limit": check_channel_limits,
    "expired_fact": checks.check_expired_facts,
    "unknown_reference": checks.check_references,
}


def check_assets(assets: Iterable[AssetCopy], ctx: RuleContext) -> RuleReport:
    """Apply every rule to every asset and return the violations in a stable order."""
    found = [v for asset in assets for check in RULES.values() for v in check(asset, ctx)]
    found.sort(key=lambda v: (v.asset_id, v.field or "", v.start or 0, v.rule, v.quote))
    return RuleReport(violations=found)


def check_asset(asset: AssetCopy, ctx: RuleContext) -> RuleReport:
    """Apply every rule to one asset."""
    return check_assets([asset], ctx)
