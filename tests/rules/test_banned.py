import pytest

from tests.rules.helpers import NO_BREAK_SPACE, ZERO_WIDTH_SPACE, brand, context, fires

WORD = "banned_word"
TYPE = "banned_claim_type"
FULL_WIDTH = "".join(chr(ord(letter) + 0xFEE0) for letter in "miracle")

WORD_CATCHES = [
    "A miracle in every cup.",
    "MIRACLE beans.",
    "Small miracles happen.",
    "A real game changer.",
    "A real game-changer.",
    "A real gamechanger.",
    f"Game{NO_BREAK_SPACE}changers only.",
    "Truly artisanal.",
    f"Mir{ZERO_WIDTH_SPACE}acle beans.",
    FULL_WIDTH + " beans.",
]
WORD_NEAR_MISSES = [
    "A miraculous finish.",
    "The game changed in 2020.",
    "An artisan baker down the road.",
    "Admiracle is a made-up word.",
]

TYPE_CATCHES = [
    ("health", "Reduces anxiety."),
    ("environmental", "Compostable bags."),
    ("superlative", "The best roast."),
    ("pricing", "Only $18."),
    ("pricing", "Free shipping."),
    ("testimonial", "Customers love it."),
    ("testimonial", '"Lovely." - Sam Lee'),
    ("testimonial", "Jordan Miller says it is great."),
    ("statistic", "9 in 10 subscribers renew."),
    ("statistic", "94% of owners still ride."),
    ("statistic", "12 percent of the harvest."),
    ("statistic", "2x the range."),
    ("statistic", "Lasts 3 times as long."),
    ("statistic", "2 million cups served."),
    ("comparison", "Smoother than a dark roast."),
    ("comparison", "More balanced than a blend."),
    ("comparison", "Compared to last year."),
    ("comparison", "Filter versus espresso."),
    ("comparison", "Filter vs. espresso."),
    ("comparison", "It outperforms steel."),
    ("comparison", "It outlasts steel."),
]
TYPE_NEAR_MISSES = [
    ("statistic", "12 oz bags ship Monday."),
    ("statistic", "A 500 W motor."),
    ("comparison", "Better than ever."),
    ("comparison", "Rather than rush, we rest the beans."),
    ("comparison", "Anything other than filter."),
    ("comparison", "Arrives earlier than planned."),
    ("comparison", "More than a morning ritual."),
]


@pytest.mark.parametrize("text", WORD_CATCHES)
def test_banned_word_catches(text: str) -> None:
    assert fires(WORD, text)


@pytest.mark.parametrize("text", WORD_NEAR_MISSES)
def test_banned_word_allows_near_miss(text: str) -> None:
    assert not fires(WORD, text)


def test_no_banned_words_means_nothing_fires() -> None:
    assert not fires(WORD, "A miracle.", ctx=context(brand=brand(banned_words=[])))


@pytest.mark.parametrize(("claim_type", "text"), TYPE_CATCHES)
def test_banned_claim_type_catches(claim_type: str, text: str) -> None:
    assert fires(TYPE, text, ctx=context(brand=brand(banned_claim_types=[claim_type])))


@pytest.mark.parametrize(("claim_type", "text"), TYPE_NEAR_MISSES)
def test_banned_claim_type_allows_near_miss(claim_type: str, text: str) -> None:
    assert not fires(TYPE, text, ctx=context(brand=brand(banned_claim_types=[claim_type])))


def test_type_that_is_not_banned_does_not_fire() -> None:
    assert not fires(TYPE, "9 in 10 subscribers renew.")


def test_a_banned_type_beats_an_approved_fact() -> None:
    ctx = context(brand=brand(banned_claim_types=["superlative"]))
    text = "Best Espresso, 2026 Cup Awards"
    assert fires(TYPE, text, ("F-004",), ctx)
    assert not fires("superlative_claim", text, ("F-004",), ctx)
