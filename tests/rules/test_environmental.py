import pytest

from tests.rules.helpers import NO_BREAK_HYPHEN, fires

RULE = "environmental_claim"

MUST_CATCH = [
    "Eco-friendly packaging.",
    "An ecofriendly choice.",
    "Go green this spring.",
    "Going green on your commute.",
    "The greener choice.",
    "A green alternative to driving.",
    "Sustainable coffee.",
    "Sustainably grown.",
    "Our sustainability promise.",
    "Carbon-neutral delivery.",
    "Carbon negative roasting.",
    "Net-zero by design.",
    "Zero emissions on every trip.",
    "Emission-free commuting.",
    "Lower tailpipe emissions.",
    "Cuts your emissions.",
    "Shrink your carbon footprint.",
    "Climate-friendly beans.",
    "Planet-friendly bags.",
    "Earth friendly.",
    "Save the planet one ride at a time.",
    "Good for the planet.",
    "Kinder to the earth.",
    "Better for the environment.",
    "Environmentally friendly.",
    "Biodegradable pods.",
    "Compostable bags.",
    "Recyclable tins.",
    "Made with recycled steel.",
    "Plastic-free shipping.",
    "Ethically sourced beans.",
    "Responsibly sourced.",
    "Fair trade certified.",
    "Organic beans.",
    "All-natural flavor.",
    "Powered by clean energy.",
    "Renewable electricity.",
    "We buy carbon offsets.",
    "Non-toxic coatings.",
    f"ECO{NO_BREAK_HYPHEN}FRIENDLY",
]

NEAR_MISSES = [
    "Green coffee beans arrive weekly.",
    "Our green paint job turns heads.",
    "You have the green light.",
    "Sustained speeds on long climbs.",
    "A carbon fork soaks up bumps.",
    "Carbon fiber frame.",
    "Organic growth in new cities.",
    "Clean design, simple controls.",
    "Natural process coffee from Huila.",
    "Fair prices are a matter of trade.",
    "The earth tones of this frame.",
    "Plastic bottle cages fit easily.",
]


@pytest.mark.parametrize("text", MUST_CATCH)
def test_catches(text: str) -> None:
    assert fires(RULE, text)


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_allows_near_miss(text: str) -> None:
    assert not fires(RULE, text)


def test_approved_wording_with_citation_is_allowed() -> None:
    assert not fires(RULE, "Our roastery runs on 100% renewable electricity.", ("F-003",))


def test_broader_wording_than_the_fact_is_caught() -> None:
    assert fires(RULE, "Everything we do runs on renewable electricity.", ("F-003",))


def test_expired_fact_no_longer_covers_the_claim() -> None:
    assert fires(RULE, "Our bags are compostable.", ("F-009",))


def test_approved_phrasing_with_citation_is_allowed() -> None:
    assert not fires(RULE, "Made with 40% recycled steel.", ("F-012",))


def test_fact_of_another_type_does_not_cover_identical_wording() -> None:
    assert fires(RULE, "Compostable liners ship with every order.", ("F-011",))


def test_approved_wording_does_not_excuse_another_claim_beside_it() -> None:
    text = "Our roastery runs on 100% renewable electricity. Every bag is biodegradable."
    assert fires(RULE, text, ("F-003",))
