"""The deterministic rules. Each check takes an asset and a context and yields violations."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

from adlantis.rules import lexicon as lx
from adlantis.rules import lexicon_commercial as lc
from adlantis.rules.context import RuleContext
from adlantis.rules.text import (
    Hit,
    bounded,
    find_hits,
    fold,
    is_inside,
    normalize,
    phrase_pattern,
    sentences,
    wording_spans,
)
from adlantis.schemas.assets import AssetCopy
from adlantis.schemas.brand import Competitor
from adlantis.schemas.channels import SECTION_CHANNELS
from adlantis.schemas.claims import ClaimType
from adlantis.schemas.rules import RuleId, RuleViolation

Violations = Iterator[RuleViolation]

DETECTORS: dict[ClaimType, tuple[re.Pattern[str], ...]] = {
    "health": (lx.HEALTH,),
    "environmental": (lx.ENVIRONMENTAL,),
    "superlative": (lx.SUPERLATIVE,),
    "pricing": (lc.MONEY, lc.PRICING_TERMS),
    "testimonial": (lc.TESTIMONIAL_TERMS, lc.ATTRIBUTED_QUOTE, lc.NAMED_SPEAKER),
    "statistic": (lc.STATISTIC,),
    "comparison": (lc.COMPARISON,),
}
_FACT_QUOTE = re.compile(r'^"(?P<text>[^"]+)"\s*[-,]\s*(?P<fact>F-\d{3})\.?$')
_TESTIMONIAL_WORDS = frozenset({"testimonial", "testimonials"})
_AMOUNT = re.compile(r"\d[\d,]*(?:\.\d{1,2})?")
_FIX_APPROVED = "Remove it, or cite an approved fact and use its approved wording verbatim."


def _fields(asset: AssetCopy) -> Iterator[tuple[str, str]]:
    for name, raw in asset.fields.items():
        yield name, normalize(raw)


def _at(rule: RuleId, asset: AssetCopy, field: str, hit: Hit, **details: object) -> RuleViolation:
    return RuleViolation(
        rule=rule,
        asset_id=asset.asset_id,
        field=field,
        quote=hit.quote,
        start=hit.start,
        end=hit.end,
        **details,
    )


def check_banned_words(asset: AssetCopy, ctx: RuleContext) -> Violations:
    """Words the brand never uses, in any case, spacing, or plural form."""
    if not ctx.brand.banned_words:
        return
    terms = [rf"{phrase_pattern(word)}(?:s|es)?" for word in ctx.brand.banned_words]
    pattern = bounded(terms)
    for field, text in _fields(asset):
        for hit in find_hits([pattern], text):
            yield _at(
                "banned_word",
                asset,
                field,
                hit,
                message=f"{hit.quote!r} is on the brand's banned word list.",
                fix="Replace it with wording the brand allows.",
            )


def check_banned_claim_types(asset: AssetCopy, ctx: RuleContext) -> Violations:
    """Claim types the brand never makes. An approved fact cannot override this."""
    for claim_type in ctx.brand.banned_claim_types:
        for field, text in _fields(asset):
            for hit in find_hits(DETECTORS[claim_type], text):
                yield _at(
                    "banned_claim_type",
                    asset,
                    field,
                    hit,
                    claim_type=claim_type,
                    message=f"The brand does not make {claim_type} claims: {hit.quote!r}.",
                    fix="Remove the claim.",
                )


def _regulated(
    asset: AssetCopy,
    ctx: RuleContext,
    rule: RuleId,
    claim_type: ClaimType,
    label: str,
    allowed: Callable[[Hit], bool] = lambda _hit: False,
) -> Violations:
    usable = ctx.usable_facts(asset, claim_type)
    wordings = [wording for fact in usable for wording in fact.wordings]
    for field, text in _fields(asset):
        approved = wording_spans(wordings, text)
        for hit in find_hits(DETECTORS[claim_type], text):
            if not is_inside(hit, approved) and not allowed(hit):
                yield _at(
                    rule,
                    asset,
                    field,
                    hit,
                    claim_type=claim_type,
                    message=f"{label} without approved wording: {hit.quote!r}.",
                    fix=_FIX_APPROVED,
                )


def check_health(asset: AssetCopy, ctx: RuleContext) -> Violations:
    """Health and medical claims."""
    yield from _regulated(asset, ctx, "health_claim", "health", "Health claim")


def check_environmental(asset: AssetCopy, ctx: RuleContext) -> Violations:
    """Environmental and ethical-sourcing claims."""
    yield from _regulated(asset, ctx, "environmental_claim", "environmental", "Environmental claim")


def check_superlatives(asset: AssetCopy, ctx: RuleContext) -> Violations:
    """Claims of being the best, first, only, or top."""
    yield from _regulated(asset, ctx, "superlative_claim", "superlative", "Superlative")


def _quotes_a_cited_fact(hit: Hit, asset: AssetCopy, ctx: RuleContext) -> bool:
    """True for an approved fact in quotation marks, attributed to its own fact ID."""
    match = _FACT_QUOTE.match(hit.quote)
    fact = ctx.facts.get(match["fact"]) if match else None
    if fact is None or fact.id not in asset.references or fact.is_expired(ctx.today):
        return False
    return fold(match["text"]) in {fold(wording) for wording in fact.wordings}


def _names_the_word(hit: Hit, asset: AssetCopy) -> bool:
    """True when a campaign plan only refers to a testimonial and does not give one."""
    return asset.channel in SECTION_CHANNELS and hit.quote.casefold() in _TESTIMONIAL_WORDS


def check_testimonials(asset: AssetCopy, ctx: RuleContext) -> Violations:
    """Customer quotes, ratings, reviews, and endorsements."""
    yield from _regulated(
        asset,
        ctx,
        "testimonial_claim",
        "testimonial",
        "Testimonial or endorsement",
        lambda hit: _quotes_a_cited_fact(hit, asset, ctx) or _names_the_word(hit, asset),
    )


def _amounts(text: str) -> set[tuple[str, float]]:
    found = set()
    for hit in find_hits([lc.MONEY], text):
        number = _AMOUNT.search(hit.quote)
        symbol = hit.quote[0] if hit.quote[0] in "€£" else "$"
        if re.search(r"eur", hit.quote, re.IGNORECASE):
            symbol = "€"
        elif re.search(r"gbp", hit.quote, re.IGNORECASE):
            symbol = "£"
        found.add((symbol, float(number.group().replace(",", ""))))
    return found


def check_pricing(asset: AssetCopy, ctx: RuleContext) -> Violations:
    """Prices must match a cited fact; offers and guarantees must use its exact wording."""
    usable = ctx.usable_facts(asset, "pricing")
    wordings = [wording for fact in usable for wording in fact.wordings]
    allowed = {amount for wording in wordings for amount in _amounts(normalize(wording))}
    for field, text in _fields(asset):
        approved = wording_spans(wordings, text)
        for hit in find_hits(DETECTORS["pricing"], text):
            is_price = lc.MONEY.fullmatch(hit.quote) is not None
            if is_inside(hit, approved) or (is_price and _amounts(hit.quote) <= allowed):
                continue
            yield _at(
                "pricing_claim",
                asset,
                field,
                hit,
                claim_type="pricing",
                message=f"Pricing claim without an approved source: {hit.quote!r}.",
                fix=_FIX_APPROVED,
            )


def _competitor_pattern(competitor: Competitor) -> re.Pattern[str]:
    return bounded(rf"{phrase_pattern(name)}(?:'s)?" for name in competitor.names)


def _is_competitor_mention(quote: str, competitor: Competitor) -> bool:
    return not (competitor.common_word and quote.islower())


def check_competitors(asset: AssetCopy, ctx: RuleContext) -> Violations:
    """Competitors are never compared against or criticized."""
    for field, text in _fields(asset):
        for hit in find_hits([lc.GENERIC_DISPARAGEMENT], text):
            yield _at(
                "competitor_disparagement",
                asset,
                field,
                hit,
                message=f"Disparages competitors: {hit.quote!r}.",
                fix="Describe the product on its own merits.",
            )
        for offset, sentence in sentences(text):
            yield from _disparaged_in(asset, ctx, field, offset, sentence)


def _disparaged_in(
    asset: AssetCopy, ctx: RuleContext, field: str, offset: int, sentence: str
) -> Violations:
    if not lc.DISPARAGING.search(sentence):
        return
    for competitor in ctx.brand.competitors:
        for match in _competitor_pattern(competitor).finditer(sentence):
            if _is_competitor_mention(match.group(), competitor):
                hit = Hit(offset, offset + len(sentence), sentence.strip())
                yield _at(
                    "competitor_disparagement",
                    asset,
                    field,
                    hit,
                    message=f"Compares against or criticizes {competitor.name}.",
                    fix="Remove the competitor from the sentence.",
                )
                break


def check_expired_facts(asset: AssetCopy, ctx: RuleContext) -> Violations:
    """Expired facts may be neither cited nor repeated."""
    expired = [fact for fact in ctx.facts.facts if fact.is_expired(ctx.today)]
    for fact in expired:
        if fact.id in asset.references:
            yield RuleViolation(
                rule="expired_fact",
                asset_id=asset.asset_id,
                quote=fact.id,
                message=f"{fact.id} expired on {fact.expires}.",
                fix="Remove the reference and the claim that relies on it.",
            )
        for field, text in _fields(asset):
            for start, end in wording_spans(fact.wordings, text):
                hit = Hit(start, end, text[start:end])
                yield _at(
                    "expired_fact",
                    asset,
                    field,
                    hit,
                    message=f"Repeats {fact.id}, which expired on {fact.expires}.",
                    fix="Remove the claim.",
                )


def check_references(asset: AssetCopy, ctx: RuleContext) -> Violations:
    """Every reference must name a fact on the sheet or an evidence record."""
    for reference in asset.references:
        is_evidence = re.fullmatch(r"E-\d+", reference) is not None
        unknown_evidence = (
            is_evidence and ctx.evidence_ids is not None and reference not in ctx.evidence_ids
        )
        if unknown_evidence or (not is_evidence and ctx.facts.get(reference) is None):
            yield RuleViolation(
                rule="unknown_reference",
                asset_id=asset.asset_id,
                quote=reference,
                message=f"{reference} is not an approved fact or evidence record.",
                fix="Cite an existing fact or evidence ID.",
            )
