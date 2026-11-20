import pytest

from tests.rules.helpers import fires

RULE = "testimonial_claim"

MUST_CATCH = [
    "Customers say it changed their mornings.",
    "Our customers love it.",
    "Customers rave about the crema.",
    "Rated 4.9 stars.",
    "A rating of 4.8 out of 5.",
    "A 5-star roast.",
    "Five-star service.",
    "As seen in the morning papers.",
    "Featured on national radio.",
    "Endorsed by champions.",
    "Recommended by baristas nationwide.",
    "Approved by professional riders.",
    "Trusted by commuters everywhere.",
    "Loved by coffee lovers.",
    "Chosen by the pros.",
    "Used by professional baristas.",
    "Doctors recommend it.",
    "Experts agree.",
    "Baristas choose this roast.",
    "Riders prefer the Arc 7.",
    "Thousands of happy customers.",
    "Satisfied customers return.",
    "Read our testimonials.",
    "Reviewers call it stunning.",
    "It earned rave reviews.",
    "A verified buyer wrote in.",
    '"Changed my life." - Alex Morgan',
    '"Best thing ever", Sam Lee',
    '"Worth every penny," said Jo',
    "Jordan Miller says it is great.",
]

NEAR_MISSES = [
    "Our customer service team is here.",
    "Say hello to the new harvest.",
    "The recommended grind size is medium.",
    "We recommend a 1:16 ratio.",
    "Star anise and clove on the nose.",
    "A trusted method for brewing.",
    "Parts are easy to find.",
    'Try the "Slow Sunday" blend.',
    'Our roast is called "Morning Light" for a reason.',
    "Rated 500 W motor.",
    "Riders can adjust the saddle.",
    "Reviews of our brew guide are welcome.",
]


@pytest.mark.parametrize("text", MUST_CATCH)
def test_catches(text: str) -> None:
    assert fires(RULE, text)


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_allows_near_miss(text: str) -> None:
    assert not fires(RULE, text)


def test_approved_quote_with_citation_is_allowed() -> None:
    assert not fires(RULE, '"My mornings start here now." - Priya N., subscriber', ("F-007",))


def test_approved_quote_without_citation_is_caught() -> None:
    assert fires(RULE, '"My mornings start here now." - Priya N., subscriber')


def test_altered_quote_is_caught_even_with_a_citation() -> None:
    assert fires(RULE, '"My mornings are better now." - Priya N., subscriber', ("F-007",))
