"""Channel length limits and the counting method each platform uses."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

from adlantis.config.models import CONFIG_DIR
from adlantis.schemas.channels import Channel, ChannelLimits, CountingMethod

CHANNEL_LIMITS_PATH = CONFIG_DIR / "channel_limits.yaml"
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_X_URL_WEIGHT = 23
_X_LIGHT_RANGES = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
_ZWJ = 0x200D
_NO_WIDTH = {_ZWJ, 0xFE0F, *range(0x1F3FB, 0x1F400)}
_FLAG_LETTERS = range(0x1F1E6, 0x1F200)


@lru_cache(maxsize=4)
def load_channel_limits(path: Path = CHANNEL_LIMITS_PATH) -> ChannelLimits:
    """Read and validate the channel limits."""
    return ChannelLimits.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def count_length(text: str, method: CountingMethod) -> int:
    """Measure `text` the way the platform measures it."""
    text = unicodedata.normalize("NFC", text)
    if method == "double_width":
        return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    if method == "x_weighted":
        return _x_weighted(text)
    return len(text)


def _x_weighted(text: str) -> int:
    urls = _URL.findall(text)
    total = _X_URL_WEIGHT * len(urls)
    joined, flag_open = False, False
    for char in _URL.sub("", text):
        code = ord(char)
        if code in _NO_WIDTH:
            joined = joined or code == _ZWJ
            continue
        if code in _FLAG_LETTERS and flag_open:
            flag_open = False
            continue
        flag_open = code in _FLAG_LETTERS
        if not joined:
            total += 1 if any(low <= code <= high for low, high in _X_LIGHT_RANGES) else 2
        joined = False
    return total


def required_mentions(channel: Channel, product_name: str) -> dict[str, str]:
    """The fields that must name the product, when the name fits within the field's limit."""
    if channel != "search_ad" or not product_name.strip():
        return {}
    limit = load_channel_limits().channels["search_ad"]["headline"].max_chars
    return {"headline": product_name} if len(product_name) <= limit else {}


def key_message_limit(channel: Channel) -> int | None:
    """How early an Instagram caption must state its key message, before "see more" hides it."""
    if channel != "instagram":
        return None
    return load_channel_limits().channels["instagram"]["caption"].target_chars
