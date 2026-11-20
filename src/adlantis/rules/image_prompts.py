"""Code checks on image prompts: no real people, no real brands, and no logos."""

from __future__ import annotations

import re
from collections.abc import Iterable

from adlantis.rules.negation import without_negated
from adlantis.rules.text import normalize
from adlantis.schemas.brand import BrandKit

SAFETY_SUFFIX = (
    "Entirely fictional scene. Show no logos, no brand names, no readable text, "
    "and no recognizable real people."
)
_MARKS = re.compile(
    r"(?<!\w)(?:logos?|logotypes?|wordmarks?|trademarks?|brand\s*marks?|brand(?:ed|ing)"
    r"|emblems?|insignias?|mascots?)(?!\w)",
    re.IGNORECASE,
)
_PEOPLE = re.compile(
    r"(?<!\w)(?:celebrit(?:y|ies)|famous|public\s+figures?|politicians?|influencers?"
    r"|real\s+(?:person|people)|actual\s+(?:person|people)|likeness(?:es)?"
    r"|look-?alikes?|in\s+the\s+style\s+of)(?!\w)",
    re.IGNORECASE,
)
_NAMED_PERSON = re.compile(
    r"\b(?:[Pp]ortrait|[Pp]hoto|[Pp]hotograph|[Pp]icture|[Ii]mage|[Pp]ainting|[Dd]rawing)\s+of\s+"
    r"[A-Z][a-z]+\s+[A-Z][a-z]+\b"
    r"|\b(?:Mr|Mrs|Ms|Dr|President|Senator|Governor)\.?\s+[A-Z][a-z]+\b"
)
_REAL_BRANDS = re.compile(
    r"(?<!\w)(?:starbucks|nespresso|keurig|dunkin|lavazza|folgers|nescaf[eé]|illy|chemex|hario"
    r"|aeropress|breville|nike|adidas|coca-?cola|pepsi|google|amazon|facebook|instagram|tiktok"
    r"|microsoft|samsung|tesla|cannondale|shimano|bosch|ikea|mcdonald'?s|disney|marvel|rolex"
    r"|gucci|chanel|louis\s+vuitton|ferrari|bmw|mercedes|toyota|iphone|macbook)(?!\w)",
    re.IGNORECASE,
)


def image_prompt_problems(
    text: str, brand: BrandKit, product_names: Iterable[str] = ()
) -> list[str]:
    """Every reason this prompt may not be used. An empty list means it passes."""
    full = normalize(text)
    clean = without_negated(full)
    problems: list[str] = []
    if _MARKS.search(clean):
        problems.append("requests a logo or brand mark")
    if _PEOPLE.search(clean) or _NAMED_PERSON.search(clean):
        problems.append("requests a real person")
    if _REAL_BRANDS.search(clean):
        problems.append("names a real brand")
    competitors = [name for competitor in brand.competitors for name in competitor.names]
    names = [brand.name, *brand.aliases, *product_names, *competitors]
    if any(_mentions(name, clean) for name in names if name.strip()):
        problems.append("names a brand or product, which would appear in the image")
    if any(_mentions(word, full) for word in brand.banned_words):
        problems.append("uses a banned word")
    return problems


def with_safety_suffix(prompt: str) -> str:
    """The prompt as it is sent, with the standing restrictions added by code."""
    return f"{prompt.strip()} {SAFETY_SUFFIX}"


def sendable_problems(prompt: str, brand: BrandKit, product_names: Iterable[str] = ()) -> list[str]:
    """Re-check a stored prompt immediately before it is sent for generation."""
    if not prompt.endswith(SAFETY_SUFFIX):
        return ["is missing the standing image restrictions"]
    return image_prompt_problems(prompt.removesuffix(SAFETY_SUFFIX), brand, product_names)


def _mentions(name: str, text: str) -> bool:
    words = r"\s+".join(re.escape(word) for word in normalize(name).split())
    return re.search(rf"(?<!\w){words}(?!\w)", text, re.IGNORECASE) is not None
