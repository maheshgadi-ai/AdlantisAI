"""Every inflection and alternative in the rule wording, each proven to matter on its own."""

import pytest

from tests.rules.helpers import brand, context, fires

HEALTH_VERBS = [
    "cure",
    "cures",
    "cured",
    "curing",
    "treat",
    "treats",
    "treated",
    "treating",
    "heal",
    "heals",
    "healed",
    "healing",
    "prevent",
    "prevents",
    "prevented",
    "preventing",
    "relieve",
    "relieves",
    "relieved",
    "relieving",
    "reduce",
    "reduces",
    "reduced",
    "reducing",
    "lower",
    "lowers",
    "lowered",
    "lowering",
    "ease",
    "eases",
    "eased",
    "easing",
    "soothe",
    "soothes",
    "soothed",
    "soothing",
    "fight",
    "fights",
    "fighting",
    "calm",
    "calms",
    "calmed",
    "calming",
    "beat",
    "beats",
    "beating",
]
HEALTH_CONDITIONS = [
    "anxiety",
    "depression",
    "insomnia",
    "stress",
    "pain",
    "inflammation",
    "blood pressure",
    "blood sugar",
    "cholesterol",
    "diabetes",
    "heart disease",
    "cancer",
    "arthritis",
    "fatigue",
    "obesity",
    "migraine",
    "migraines",
    "headache",
    "headaches",
    "illness",
    "illnesses",
    "disease",
    "diseases",
    "infection",
    "infections",
]
VARIANTS = {
    "health_claim": [
        "pain relief",
        "headache relief",
        "stress relieving",
        "stress reliever",
        "clinically shown",
        "medically approved",
        "doctor approved",
        "doctors recommended",
        "detoxes",
        "detoxify",
        "detoxifying",
        "boost immunity",
        "boost your immune system",
        "boost memory",
        "boost your focus",
        "improving focus",
        "sharpen your memory",
        "sharpening focus",
        "improve memory",
        "improves mood",
        "improves circulation",
        "improves your health",
        "good for your health",
        "good for your brain",
        "good for your body",
        "losing weight",
        "burning calories",
        "a healthier life",
        "a healthier lifestyle",
        "a healthier heart",
        "a healthier body",
        "the healthier choice",
    ],
    "environmental_claim": [
        "It goes green",
        "a green option",
        "a green commute",
        "a green product",
        "a greener future",
        "the green way",
        "a green ride",
        "carbon free",
        "carbon zero",
        "carbon positive",
        "reduce emissions",
        "reduced emissions",
        "reduces emissions",
        "reducing emissions",
        "cutting emissions",
        "fewer emissions",
        "less emissions",
        "no emissions",
        "climate footprint",
        "climate positive",
        "climate neutral",
        "climate smart",
        "saving the planet",
        "protects the planet",
        "protecting the earth",
        "environmentally safe",
        "environmentally responsible",
        "environmentally conscious",
        "renewable energy",
        "renewable power",
    ],
    "superlative_claim": [
        "the most advanced motor",
        "the most powerful hub",
        "the most reliable frame",
        "the most awarded roaster",
        "the most loved blend",
        "the most comfortable saddle",
        "the most efficient drive",
        "the most innovative design",
        "the most delicious cup",
        "the most flavorful roast",
        "category leading range",
        "world-leading design",
        "the leading brand",
        "the leading maker",
        "the leading manufacturer",
        "the leading provider",
        "an industry leader",
        "clinically proven",
        "the only roast with a promise",
        "the only bike to fold flat",
        "the best without compromise",
        "the best bypass around town",
        "the best iffy weather bike",
    ],
    "pricing_claim": [
        "12 eur",
        "20 euros",
        "15 GBP",
        "save 10 percent",
        "discounts for everyone",
        "0% financing",
        "0% interest",
    ],
    "testimonial_claim": [
        '"Worth it" says Jo Lee',
        "Jordan Miller said it was great",
        "Jordan Miller swears by it",
        "a customer says so",
        "customers agree",
        "a customer agrees",
        "a customer loves it",
        "a customer raves",
        "customers swear by it",
        "a customer swears by it",
        "customers rate it",
        "a customer rates it",
        "rated 4 out of 5",
        "as seen on television",
        "featured in print",
        "used by pros",
        "used by professionals",
        "used by thousands",
        "used by millions",
        "used by athletes",
        "used by experts",
        "dentists agree",
        "athletes agree",
        "chefs agree",
        "cyclists agree",
        "experts trust it",
        "reviewers say so",
        "a reviewer says so",
        "a reviewer calls it great",
        "a verified purchase",
        "a verified review",
    ],
    "competitor_disparagement": [
        "Harrowfen scams people",
        "Harrowfen is scammy",
        "Unlike the competition, we publish results",
        "Unlike rivals, we publish results",
        "Unlike big brands, we publish results",
        "Competitors can't keep up",
        "Other brands fail here",
        "Competitors cannot keep up",
        "Rivals fail here",
        "The competition fails here",
        "Rivals skimp on parts",
        "Rivals overcharge",
    ],
}
NEAR_MISSES = {
    "health_claim": ["Ease a common pain point for riders."],
    "environmental_claim": [
        "Organic traffic grew this year.",
        "Organic reach matters.",
        "Organic search brings readers.",
        "Organic results vary.",
        "Organic chemistry class.",
    ],
    "superlative_claim": [
        "Issue #1 of our newsletter.",
        "Batch #1 ships Monday.",
        "Lot #1 sold out.",
        "Tip #1: rinse the filter.",
        "Part #1 arrives first.",
        "Batch No. 1 ships Monday.",
        "Lot No. 1 is resting.",
        "Roast No. 1 is ready.",
        "Number one thousand ships today.",
        "Best wishes to you.",
        "Best enjoyed black.",
        "Best when fresh.",
        "Best with milk.",
        "Best by June.",
        "Best if used soon.",
        "Best within a month.",
        "Best practices for brewing.",
        "The only thing to do is brew.",
    ],
    "competitor_disparagement": [
        "We stock nothing other than Harrowfen mugs.",
        "We sell Harrowfen mugs rather than glasses.",
        "Harrowfen opened earlier than planned.",
        "Harrowfen opened later than planned.",
        "Harrowfen opened sooner than planned.",
    ],
}
BANNED_TYPE_VARIANTS = [
    ("statistic", "9 out of 10 subscribers renew."),
    ("statistic", "2 billion cups served."),
    ("comparison", "Less acidic than a blend."),
    ("comparison", "Compared with last year."),
]
BANNED_TYPE_NEAR_MISSES = [
    ("comparison", "Arrives later than planned."),
    ("comparison", "Arrives sooner than planned."),
]


@pytest.mark.parametrize("verb", HEALTH_VERBS)
def test_every_health_verb_form_fires(verb: str) -> None:
    assert fires("health_claim", f"It will {verb} anxiety.")


@pytest.mark.parametrize("condition", HEALTH_CONDITIONS)
def test_every_health_condition_fires(condition: str) -> None:
    assert fires("health_claim", f"It eases {condition}.")


@pytest.mark.parametrize(
    ("rule", "text"), [(rule, text) for rule, texts in VARIANTS.items() for text in texts]
)
def test_variant_fires(rule: str, text: str) -> None:
    assert fires(rule, text)


@pytest.mark.parametrize(
    ("rule", "text"), [(rule, text) for rule, texts in NEAR_MISSES.items() for text in texts]
)
def test_guarded_wording_is_allowed(rule: str, text: str) -> None:
    assert not fires(rule, text)


@pytest.mark.parametrize(("claim_type", "text"), BANNED_TYPE_VARIANTS)
def test_banned_type_variant_fires(claim_type: str, text: str) -> None:
    ctx = context(brand=brand(banned_claim_types=[claim_type]))
    assert fires("banned_claim_type", text, ctx=ctx)


@pytest.mark.parametrize(("claim_type", "text"), BANNED_TYPE_NEAR_MISSES)
def test_banned_type_guard_is_allowed(claim_type: str, text: str) -> None:
    ctx = context(brand=brand(banned_claim_types=[claim_type]))
    assert not fires("banned_claim_type", text, ctx=ctx)
