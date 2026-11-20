import pytest

from tests.rules.helpers import NO_BREAK_SPACE, SOFT_HYPHEN, ZERO_WIDTH_SPACE, fires

RULE = "health_claim"

MUST_CATCH = [
    "Reduces anxiety in minutes.",
    "This blend cures insomnia.",
    "It treats arthritis.",
    "Heals inflammation.",
    "Prevents heart disease.",
    "Relieves migraines fast.",
    "Lowers blood pressure.",
    "Lowers your blood sugar.",
    "Eases joint pain.",
    "Soothes daily stress.",
    "Fights fatigue.",
    "Calms your anxiety.",
    "Beats depression.",
    "Reducing the risk of cancer.",
    "Helps prevent diabetes and obesity.",
    "Stress relief in every cup.",
    "An anxiety-reducing blend.",
    "Clinically proven results.",
    "Medically tested.",
    "Doctor-recommended.",
    "FDA approved.",
    "A therapeutic ritual.",
    "Medicinal mushrooms inside.",
    "Detox every morning.",
    "It detoxifies your body.",
    "Anti-inflammatory compounds.",
    "An antiaging secret.",
    "Immune-boosting beans.",
    "Immune support daily.",
    "Boost your metabolism.",
    "Boosts energy all day.",
    "Boosting mood.",
    "Sharpens your focus.",
    "Improves sleep.",
    "Heart-healthy coffee.",
    "Good for your heart.",
    "Lose weight while you commute.",
    "Weight loss on two wheels.",
    "Burn more calories.",
    "Burns fat.",
    "A healthier you.",
    "Ride more and live longer.",
    "REDUCES ANXIETY",
    f"Re{ZERO_WIDTH_SPACE}duces anxi{SOFT_HYPHEN}ety",
    f"Reduces{NO_BREAK_SPACE}anxiety",
]

NEAR_MISSES = [
    "Treat yourself this weekend.",
    "Cured bacon pairs well with this roast.",
    "Ease of use on every ride.",
    "Reduce your commute time.",
    "A real pain point for commuters.",
    "The rack reduces stress on the frame.",
    "Focus on flavor.",
    "Boost your range with a second battery.",
    "The heart of the city.",
    "A frame weight of 19 kg.",
    "Reduced frame weight.",
    "Stress-free returns.",
    "We reduce waste. Stress less about packaging.",
    "Our heel-friendly pedals grip well.",
    "Lower the seat post in seconds.",
    "Medium roast with a calm finish.",
]


@pytest.mark.parametrize("text", MUST_CATCH)
def test_catches(text: str) -> None:
    assert fires(RULE, text)


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_allows_near_miss(text: str) -> None:
    assert not fires(RULE, text)


def test_approved_wording_with_citation_is_allowed() -> None:
    assert not fires(RULE, "Clinically tested for low acidity by Quenby Labs.", ("F-002",))


def test_approved_wording_without_citation_is_caught() -> None:
    assert fires(RULE, "Clinically tested for low acidity by Quenby Labs.")


def test_citation_does_not_cover_different_wording() -> None:
    assert fires(RULE, "Clinically tested to calm your stress.", ("F-002",))


def test_fact_of_another_type_does_not_cover_the_claim() -> None:
    assert fires(RULE, "Clinically tested for low acidity by Quenby Labs.", ("F-001",))
