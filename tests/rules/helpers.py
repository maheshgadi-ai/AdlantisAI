"""A small fictional brand and fact sheet for exercising the rules."""

from __future__ import annotations

from datetime import date

from adlantis.rules import RuleContext, check_asset
from adlantis.schemas import ApprovedFact, AssetCopy, BrandKit, FactSheet, RuleReport

TODAY = date(2026, 11, 18)

# Characters used to disguise banned wording.
ZERO_WIDTH_SPACE = chr(0x200B)
SOFT_HYPHEN = chr(0x00AD)
NO_BREAK_SPACE = chr(0x00A0)
NO_BREAK_HYPHEN = chr(0x2011)


def brand(**changes: object) -> BrandKit:
    values: dict[str, object] = {
        "name": "Sample Roasters",
        "voice": {"tone": ["warm"], "do": ["Be plain."], "dont": ["Boast."]},
        "audience": "Home brewers",
        "values": ["honesty"],
        "colors": [{"name": "Moss", "hex": "#3F5B45"}],
        "banned_words": ["miracle", "game changer", "artisanal"],
        "competitors": [
            {"name": "Harrowfen Coffee", "aliases": ["Harrowfen"]},
            {"name": "Apex", "common_word": True},
        ],
    }
    return BrandKit.model_validate({**values, **changes})


def fact(fact_id: str, claim_type: str, claim: str, **changes: object) -> ApprovedFact:
    return ApprovedFact.model_validate(
        {"id": fact_id, "claim_type": claim_type, "claim": claim, "evidence_note": "On file."}
        | changes
    )


SHEET = FactSheet(
    facts=[
        fact("F-001", "product_fact", "Roasted within 48 hours of shipping."),
        fact("F-002", "health", "Clinically tested for low acidity by Quenby Labs."),
        fact("F-003", "environmental", "Our roastery runs on 100% renewable electricity."),
        fact("F-004", "superlative", "Best Espresso, 2026 Cup Awards"),
        fact(
            "F-005",
            "pricing",
            "Single-origin bags cost $18 for 12 oz.",
            wording="paraphrase",
            paraphrase_scope="Keep the price and size.",
            approved_phrasings=["$18 per 12 oz bag"],
        ),
        fact("F-006", "pricing", "Free shipping on orders over $40."),
        fact("F-007", "testimonial", '"My mornings start here now." - Priya N., subscriber'),
        fact("F-008", "pricing", "Holiday bundle is $30.", expires=date(2026, 1, 31)),
        fact("F-009", "environmental", "Our bags are compostable.", expires=date(2026, 6, 30)),
        fact("F-010", "superlative", "Top-rated roaster, 2026 Valley Guide", expires=TODAY),
        fact("F-011", "product_fact", "Compostable liners ship with every order."),
        fact(
            "F-012",
            "environmental",
            "Mill certificates confirm 40% recycled steel in the frame.",
            wording="paraphrase",
            paraphrase_scope="Keep the percentage and the material.",
            approved_phrasings=["Made with 40% recycled steel."],
        ),
        fact("F-013", "pricing", "The Arc costs $2,199."),
    ]
)


def context(**changes: object) -> RuleContext:
    return RuleContext(**{"brand": brand(), "facts": SHEET, "today": TODAY, **changes})


def asset(text: str, refs: tuple[str, ...] = (), channel: str = "instagram") -> AssetCopy:
    field = {"instagram": "caption", "x": "post", "linkedin": "post"}[channel]
    return AssetCopy(asset_id="a1", channel=channel, fields={field: text}, references=list(refs))


def report(text: str, refs: tuple[str, ...] = (), ctx: RuleContext | None = None) -> RuleReport:
    return check_asset(asset(text, refs), ctx or context())


def fires(rule: str, text: str, refs: tuple[str, ...] = (), ctx: RuleContext | None = None) -> bool:
    return bool(report(text, refs, ctx).for_rule(rule))
