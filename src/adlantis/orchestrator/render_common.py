"""Wording and safety helpers shared by the kit's output formats."""

from __future__ import annotations

from urllib.parse import urlsplit

from adlantis.schemas.kit import CampaignKit

BASELINE_NOTICE = (
    "Baseline run for evaluation. Its claims were not verified, and it cannot be approved."
)
DRAFT_NOTICE = "Draft. This kit is not approved for use until a person signs off."
CHANNEL_TITLES = {
    "search_ad": "Search ads",
    "meta_ad": "Meta ads",
    "instagram": "Instagram",
    "linkedin": "LinkedIn",
    "x": "X",
    "email": "Email",
    "landing_page": "Landing page",
    "strategy": "Strategy",
    "image_prompt": "Image prompt",
}


def status_line(kit: CampaignKit) -> str:
    """The kit's sign-off state in one sentence."""
    if kit.mode == "baseline":
        return BASELINE_NOTICE
    if kit.approval is None:
        return DRAFT_NOTICE
    when = kit.approval.approved_at.strftime("%Y-%m-%d %H:%M UTC")
    return f"Approved by {kit.approval.approved_by} on {when}."


def safe_url(url: str) -> str:
    """The URL when it is a plain web link, otherwise an empty string."""
    if any(char.isspace() or char in "<>\"'()" for char in url):
        return ""
    parts = urlsplit(url)
    return url if parts.scheme in {"http", "https"} and parts.netloc else ""
