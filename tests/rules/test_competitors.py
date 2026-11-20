import pytest

from tests.rules.helpers import fires

RULE = "competitor_disparagement"

MUST_CATCH = [
    "Harrowfen Coffee is worse.",
    "Harrowfen is inferior.",
    "Harrowfen tastes bad.",
    "Harrowfen roasts poorly.",
    "Harrowfen makes a weak cup.",
    "Harrowfen is overpriced.",
    "Harrowfen sells cheap beans.",
    "Harrowfen is a rip-off.",
    "Harrowfen is a scam.",
    "Harrowfen sells fake origins.",
    "Harrowfen is unreliable.",
    "Harrowfen bags are flimsy.",
    "Harrowfen beans are stale.",
    "Harrowfen beans taste burnt.",
    "Harrowfen is bland.",
    "Harrowfen is terrible.",
    "Harrowfen is awful.",
    "Harrowfen is mediocre.",
    "Harrowfen feels outdated.",
    "Harrowfen fails every test.",
    "Harrowfen lags behind.",
    "Our roast beats Harrowfen.",
    "Our roast crushes Harrowfen.",
    "Our roast destroys Harrowfen.",
    "We are superior to Harrowfen.",
    "We outperform Harrowfen.",
    "Smoother than Harrowfen.",
    "More flavorful than Harrowfen.",
    "Unlike Harrowfen, we care.",
    "Choose us instead of Harrowfen.",
    "Ditch Harrowfen today.",
    "Forget Harrowfen.",
    "Harrowfen can't match this.",
    "Harrowfen is no match for us.",
    "Harrowfen's beans are stale.",
    "harrowfen coffee is overpriced.",
    "harrowfen is overpriced.",
    "HARROWFEN IS OVERPRICED.",
    "Apex is overpriced.",
    "Unlike our competitors, we roast weekly.",
    "Unlike other brands, we publish our sources.",
    "The competition can't keep up.",
    "Rivals cut corners.",
]

NEAR_MISSES = [
    "Harrowfen Coffee opened a new shop downtown.",
    "Our racks fit Harrowfen mugs.",
    "Harrowfen is a neighbor. Our beans are never stale.",
    "We reached the apex of the climb and it was awful.",
    "Other brands of filters work fine.",
    "Smoother than our last harvest.",
    "A competitive cycling heritage.",
]


@pytest.mark.parametrize("text", MUST_CATCH)
def test_catches(text: str) -> None:
    assert fires(RULE, text)


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_allows_near_miss(text: str) -> None:
    assert not fires(RULE, text)


def test_an_approved_fact_never_excuses_disparagement() -> None:
    assert fires(RULE, "Harrowfen is terrible. Roasted within 48 hours of shipping.", ("F-001",))
