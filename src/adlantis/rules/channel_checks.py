"""The channel length rule."""

from __future__ import annotations

from collections.abc import Iterator

from adlantis.rules.channels import count_length
from adlantis.rules.context import RuleContext
from adlantis.schemas.assets import AssetCopy
from adlantis.schemas.channels import SECTION_CHANNELS
from adlantis.schemas.rules import RuleViolation


def check_channel_limits(asset: AssetCopy, ctx: RuleContext) -> Iterator[RuleViolation]:
    """Every field must be known to its channel and fit within its limit."""
    if asset.channel in SECTION_CHANNELS:  # strategy and image prompts are not published copy
        return
    limits = ctx.limits.channels.get(asset.channel, {})
    for field, raw in asset.fields.items():
        limit = limits.get(field)
        base = {"rule": "channel_limit", "asset_id": asset.asset_id, "field": field}
        if limit is None:
            known = ", ".join(sorted(limits)) or "none"
            message = f"{asset.channel} has no field named {field!r}. Known fields: {known}."
            yield RuleViolation(**base, message=message, fix="Use a known field.")
            continue
        length = count_length(raw, limit.counting)
        if length > limit.max_chars:
            yield RuleViolation(
                **base,
                severity=limit.severity,
                quote=raw[:60],
                message=f"{length} characters exceeds the {limit.max_chars} allowed.",
                fix=f"Shorten by at least {length - limit.max_chars} characters.",
            )
        elif limit.truncation and length > limit.truncation.max_chars:
            yield RuleViolation(
                **base,
                severity=limit.truncation.severity,
                quote=raw[:60],
                message=(
                    f"{length} characters passes the 'see more' point "
                    f"at {limit.truncation.max_chars}."
                ),
                fix="Put the key message before the fold, or shorten the copy.",
            )
