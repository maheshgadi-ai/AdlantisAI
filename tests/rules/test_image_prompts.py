"""Image prompts can never request real people, real brands, or logos."""

import pytest

from adlantis.rules.image_prompts import (
    SAFETY_SUFFIX,
    image_prompt_problems,
    sendable_problems,
    with_safety_suffix,
)
from tests.rules.helpers import brand

PRODUCT = ("Hollow Reserve", "Hollow Reserve Coffee")


def problems(text: str) -> list[str]:
    return image_prompt_problems(text, brand(aliases=["Sample"]), PRODUCT)


@pytest.mark.parametrize(
    "text",
    [
        "A bag with our logo on the front.",
        "Show the LOGOS of three roasters.",
        "A cup with a wordmark.",
        "A registered trademark on the wall.",
        "A branded apron.",
        "The company emblem above the door.",
        "A brand mark on the cup.",
        "A cheerful mascot pouring coffee.",
    ],
)
def test_logos_are_refused(text: str) -> None:
    assert "requests a logo or brand mark" in problems(text)


@pytest.mark.parametrize(
    "text",
    [
        "A celebrity drinking coffee.",
        "A famous actor at the counter.",
        "A public figure on a bike.",
        "A politician at a cafe.",
        "An influencer holding a cup.",
        "A real person from the news.",
        "The likeness of a singer.",
        "A lookalike of a film star.",
        "A painting in the style of a modern master.",
        "A portrait of Dana Reyes at home.",
        "Photo of Marcus Hale riding to work.",
        "Dr. Okafor pouring a cup.",
        "President Lang tasting coffee.",
    ],
)
def test_real_people_are_refused(text: str) -> None:
    assert "requests a real person" in problems(text)


@pytest.mark.parametrize(
    "text",
    [
        "A Starbucks cup on a desk.",
        "A Chemex on the counter.",
        "Someone wearing Nike shoes.",
        "An iPhone beside the mug.",
        "A rider with Shimano gears.",
        "A Coca-Cola sign.",
        "A Louis Vuitton bag.",
    ],
)
def test_real_brands_are_refused(text: str) -> None:
    assert "names a real brand" in problems(text)


@pytest.mark.parametrize(
    "text",
    [
        "A bag of Hollow Reserve on a table.",
        "The Sample Roasters storefront.",
        "A Sample sign.",
        "A Harrowfen Coffee delivery van.",
        "A Harrowfen cup.",
    ],
)
def test_campaign_and_competitor_names_are_refused(text: str) -> None:
    assert "names a brand or product, which would appear in the image" in problems(text)


def test_banned_words_are_refused() -> None:
    assert "uses a banned word" in problems("A miracle sunrise over the hills.")


def test_disguised_logo_request_is_refused() -> None:
    assert problems(f"A lo{chr(0x200B)}go on a mug.")


@pytest.mark.parametrize(
    "text",
    [
        "A ceramic mug on an oak table in soft morning light.",
        "Red apple slices beside a pour-over cone.",
        "An anonymous rider seen from behind on a wet city street.",
        "A brand new kettle steaming on a stove.",
        "Hands cupping a warm mug.",
        "A logical arrangement of beans in rows.",
        "A photo of rolling green hills at dawn.",
        "An image of Colombian coffee farms.",
        "The real texture of roasted beans.",
        "A portrait orientation of a quiet kitchen.",
    ],
)
def test_ordinary_scenes_pass(text: str) -> None:
    assert problems(text) == []


def test_blank_names_are_ignored() -> None:
    assert image_prompt_problems("A quiet table.", brand(aliases=[" "]), ("",)) == []


def test_suffix_is_added_to_every_prompt() -> None:
    assert with_safety_suffix(" A quiet table. ") == f"A quiet table. {SAFETY_SUFFIX}"


def test_prompt_with_its_suffix_may_be_sent() -> None:
    assert sendable_problems(with_safety_suffix("A quiet table."), brand(), PRODUCT) == []


def test_prompt_without_its_suffix_may_not_be_sent() -> None:
    assert sendable_problems("A quiet table.", brand(), PRODUCT) == [
        "is missing the standing image restrictions"
    ]


def test_stored_prompt_is_checked_again_before_sending() -> None:
    stored = with_safety_suffix("A cup with a logo.")
    assert sendable_problems(stored, brand(), PRODUCT) == ["requests a logo or brand mark"]
