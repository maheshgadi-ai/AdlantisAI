import pytest

from tests.rules.helpers import fires

RULE = "pricing_claim"

MUST_CATCH = [
    "Only $19 a bag.",
    "From €25.",
    "Just £12.50.",
    "Yours for 20 dollars.",
    "Under 30 bucks.",
    "Priced at 45 USD.",
    "Free shipping today.",
    "Free delivery in town.",
    "Free returns, always.",
    "Start a free trial.",
    "Try it for free.",
    "20% off your first order.",
    "15 percent off.",
    "Save 10% today.",
    "Half-price Tuesdays.",
    "A discount for subscribers.",
    "Discounted bundles.",
    "Now on sale.",
    "Check the sale price.",
    "The lowest prices around.",
    "The best price in town.",
    "We price match.",
    "Our price guarantee.",
    "Money-back promise.",
    "No hidden fees.",
    "0% APR for a year.",
    "Interest-free payments.",
    "Financing available.",
    "Pay in 4.",
    "Buy one, get one.",
    "BOGO week.",
    "A limited-time offer.",
]

NEAR_MISSES = [
    "Free time is for riding.",
    "Feel free to ask us anything.",
    "Stress-free setup.",
    "A gluten-free kitchen.",
    "Wholesale accounts welcome.",
    "Our salesperson can help.",
    "A 500 W motor.",
    "12 oz bags ship on Monday.",
    "Harvested in 2026.",
    "Take 20 minutes off your commute.",
    "Save time on your commute.",
    "Worth every minute.",
]


@pytest.mark.parametrize("text", MUST_CATCH)
def test_catches(text: str) -> None:
    assert fires(RULE, text)


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_allows_near_miss(text: str) -> None:
    assert not fires(RULE, text)


@pytest.mark.parametrize("text", ["Only $18 a bag.", "Now $18.00.", "$18 per 12 oz bag"])
def test_price_matching_a_cited_fact_is_allowed(text: str) -> None:
    assert not fires(RULE, text, ("F-005",))


def test_different_price_is_caught_even_with_a_citation() -> None:
    assert fires(RULE, "Only $17 a bag.", ("F-005",))


def test_same_number_in_another_currency_is_caught() -> None:
    assert fires(RULE, "Only €18 a bag.", ("F-005",))


def test_price_without_a_citation_is_caught() -> None:
    assert fires(RULE, "Only $18 a bag.")


def test_exact_offer_wording_is_allowed() -> None:
    assert not fires(RULE, "Free shipping on orders over $40.", ("F-006",))


def test_offer_that_drops_its_condition_is_caught() -> None:
    assert fires(RULE, "Free shipping on every order.", ("F-006",))


def test_expired_price_is_caught() -> None:
    assert fires(RULE, "Holiday bundle is $30.", ("F-008",))


def test_thousands_separator_is_read_as_one_amount() -> None:
    assert not fires(RULE, "Yours for $2,199.", ("F-013",))
    assert fires(RULE, "Yours for $2,999.", ("F-013",))
