import pytest

from tests.rules.helpers import fires

RULE = "superlative_claim"

MUST_CATCH = [
    "The #1 commuter e-bike.",
    "Ranked No. 1 in the state.",
    "The number one choice.",
    "The best coffee in town.",
    "Best-in-class range.",
    "The world's first folding cargo bike.",
    "Our first-ever subscription of this kind.",
    "First of its kind.",
    "The finest beans.",
    "The greatest cup.",
    "The fastest commuter bike.",
    "The strongest frame.",
    "The lightest e-bike.",
    "The cheapest way to commute.",
    "The smoothest cup.",
    "The freshest beans.",
    "The purest flavor.",
    "The safest ride.",
    "The quietest motor.",
    "Our most popular roast.",
    "The most trusted name.",
    "Industry-leading range.",
    "Market leading battery life.",
    "The leading roaster in Ohio.",
    "A market leader.",
    "Top-rated by riders.",
    "Top ranked.",
    "Unbeatable quality.",
    "Unmatched flavor.",
    "Unrivaled comfort.",
    "Unparalleled service.",
    "Second to none.",
    "Award-winning coffee.",
    "Scientifically proven.",
    "Lab-proven durability.",
    "Proven to last.",
    "Guaranteed to delight.",
    "The only bike that folds flat.",
    "THE BEST",
]

NEAR_MISSES = [
    "Best before March 2027.",
    "Best-before date on every bag.",
    "Best regards from the roastery.",
    "Best served at 94 degrees.",
    "Best brewed with filtered water.",
    "All the best from our team.",
    "Bring your best friend along.",
    "Decent at best in the rain.",
    "Step #1: grind the beans.",
    "Issue #10 of our newsletter.",
    "Blend No. 1 is back.",
    "Number one hundred ships today.",
    "The lightest roast we offer.",
    "Most mornings start at six.",
    "Leading edge of the fork.",
    "Leading up to harvest.",
    "The only thing left is to brew.",
    "Perfect for rainy commutes.",
]


@pytest.mark.parametrize("text", MUST_CATCH)
def test_catches(text: str) -> None:
    assert fires(RULE, text)


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_allows_near_miss(text: str) -> None:
    assert not fires(RULE, text)


def test_approved_award_wording_is_allowed() -> None:
    assert not fires(RULE, "Winner: Best Espresso, 2026 Cup Awards", ("F-004",))


def test_award_citation_does_not_license_a_general_best_claim() -> None:
    assert fires(RULE, "The best coffee in the world.", ("F-004",))


def test_fact_expiring_today_is_still_valid() -> None:
    assert not fires(RULE, "Top-rated roaster, 2026 Valley Guide", ("F-010",))
