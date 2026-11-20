"""Image prompts may rule things out, but a real request is never hidden by a nearby "no"."""

import pytest

from adlantis.rules.image_prompts import image_prompt_problems
from adlantis.rules.negation import without_negated
from tests.rules.helpers import brand

PRODUCT = ("Hollow Reserve",)


def problems(text: str) -> list[str]:
    return image_prompt_problems(text, brand(), PRODUCT)


@pytest.mark.parametrize(
    "text",
    [
        "A ceramic cup on a table, no logos.",
        "A mug without brand names.",
        "A mug without any logos or labels.",
        "A still life, no packaging, labels, logos, or text.",
        "A kitchen scene, no person's face, packaging, logos, labels, or readable text.",
        "A cup with no visible logos on it.",
        "No logos on the cup.",
        "Never show logos in the scene.",
        "Avoid logos and trademarks.",
        "Avoid showing a clean table without logos.",
        "A bare shelf free of logos.",
        "A bare shelf free from branding.",
        "A logo-free mug on a table.",
        "Excluding logos, emblems, and mascots.",
        "A farm with no celebrities or famous faces.",
        "A cafe without Starbucks cups.",
        "A cup, no Harrowfen branding.",
        "A plain bag with no Hollow Reserve lettering.",
        "No logos.\nA warm kitchen.",
    ],
)
def test_ruled_out_marks_pass(text: str) -> None:
    assert problems(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "A cup with a logo.",
        "A cup with a logo and no text.",
        "No text, but a large logo on the cup.",
        "No people, with a logo on the cup.",
        "No text and logo on the cup.",
        "No clutter, a logo on the mug.",
        "No competitor marks, only our logo.",
        "No logos except the company logo.",
        "Not just a logo on the cup.",
        "Not only logos on the wall.",
        "Do not hide the logo.",
        "Never hide the logo.",
        "Do not omit logos.",
        "Not without a logo.",
        "Without removing logos from the wall.",
        "Avoid cropping the logo.",
        "No fewer than three logos.",
        "No shortage of logos on the wall.",
        "No text. A logo on the cup.",
        "No text; a logo on the cup.",
    ],
)
def test_real_logo_requests_are_still_refused(text: str) -> None:
    assert "requests a logo or brand mark" in problems(text)


@pytest.mark.parametrize(
    "text",
    [
        "No text, with a celebrity at the counter.",
        "No logos. A famous actor pours coffee.",
    ],
)
def test_people_after_a_negation_are_still_refused(text: str) -> None:
    assert "requests a real person" in problems(text)


def test_real_brand_after_a_negation_is_still_refused() -> None:
    assert "names a real brand" in problems("No logos, with a Starbucks cup on the desk.")


def test_campaign_name_after_a_negation_is_still_refused() -> None:
    assert problems("No text. A bag of Hollow Reserve.") == [
        "names a brand or product, which would appear in the image"
    ]


def test_banned_words_are_refused_even_when_negated() -> None:
    assert "uses a banned word" in problems("A sunrise with no miracle in sight.")


def test_text_without_negation_is_unchanged() -> None:
    text = "A warm kitchen at dawn."
    assert without_negated(text) == text


def test_negator_with_nothing_after_it_is_left_alone() -> None:
    assert without_negated("Say no.") == "Say no."


def test_long_lists_are_removed_in_full() -> None:
    assert "logos" not in without_negated("No labels, tags, stickers, stamps, logos, or text.")
