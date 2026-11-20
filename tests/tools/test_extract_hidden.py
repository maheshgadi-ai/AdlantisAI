"""Text a reader cannot see never reaches the model."""

import pytest

from adlantis.tools.extract import html_to_text

SECRET = "PLANTED"
VISIBLE = "Visible paragraph about home brewing."

HIDDEN_ELEMENTS = [
    f"<div hidden>{SECRET}</div>",
    f'<div aria-hidden="true">{SECRET}</div>',
    f'<div style="display:none">{SECRET}</div>',
    f'<div style="DISPLAY : NONE">{SECRET}</div>',
    f'<div style="visibility:hidden">{SECRET}</div>',
    f'<div style="visibility:collapse">{SECRET}</div>',
    f'<div style="opacity:0">{SECRET}</div>',
    f'<div style="opacity:0.0;">{SECRET}</div>',
    f'<div style="opacity:0!important">{SECRET}</div>',
    f'<div style="font-size:0">{SECRET}</div>',
    f'<div style="font-size:0px;">{SECRET}</div>',
    f'<div style="font-size:0em">{SECRET}</div>',
    f'<div style="font-size:0rem">{SECRET}</div>',
    f'<div style="font-size:0pt">{SECRET}</div>',
    f'<div style="font-size:0%">{SECRET}</div>',
    f'<div style="height:0;overflow:hidden">{SECRET}</div>',
    f'<div style="width:0px;overflow:hidden">{SECRET}</div>',
    f'<div style="max-height:0;overflow:hidden">{SECRET}</div>',
    f'<div style="max-width:0">{SECRET}</div>',
    f'<div style="text-indent:-9999px">{SECRET}</div>',
    f'<div style="position:absolute;left:-9999px">{SECRET}</div>',
    f'<div style="position:absolute;top:-5000px">{SECRET}</div>',
    f'<div style="position:absolute;right:-5000px">{SECRET}</div>',
    f'<div style="position:absolute;bottom:-5000px">{SECRET}</div>',
    f'<div style="margin-left:-5000px">{SECRET}</div>',
    f'<div style="margin-top:-5000px">{SECRET}</div>',
    f'<div style="clip:rect(0,0,0,0)">{SECRET}</div>',
    f'<div style="clip-path:inset(50%)">{SECRET}</div>',
    f'<div style="clip-path:inset(100%)">{SECRET}</div>',
    f'<div style="transform:scale(0)">{SECRET}</div>',
    f'<div style="color:transparent">{SECRET}</div>',
    f'<div style="color:#fff;background:#fff">{SECRET}</div>',
    f'<div style="color:white;background-color:#FFFFFF">{SECRET}</div>',
    f'<div style="color:black;background:#000">{SECRET}</div>',
    f'<div style="color:rgb(0, 0, 0);background:black">{SECRET}</div>',
    f'<div class="sr-only">{SECRET}</div>',
    f'<div class="note visually-hidden">{SECRET}</div>',
    f'<div class="visuallyhidden">{SECRET}</div>',
    f'<div class="screen-reader-text">{SECRET}</div>',
    f'<div class="hidden">{SECRET}</div>',
    f'<div class="d-none">{SECRET}</div>',
    f'<div class="invisible">{SECRET}</div>',
    f"<div hidden><div>nested</div>{SECRET}</div>",
    f"<!-- {SECRET} -->",
    f'<script>var a = "{SECRET}";</script>',
    f"<template>{SECRET}</template>",
    f"<noscript>{SECRET}</noscript>",
    f'<img alt="{SECRET}" src="a.png">',
    f'<meta name="description" content="{SECRET}">',
    f'<input type="hidden" value="{SECRET}">',
]
STYLESHEET_HIDDEN = [
    (".ghost{display:none}", f'<p class="ghost">{SECRET}</p>'),
    ("p.ghost { opacity: 0 }", f'<p class="ghost">{SECRET}</p>'),
    ("#ghost{visibility:hidden}", f'<p id="ghost">{SECRET}</p>'),
    (".a, .ghost{font-size:0}", f'<p class="ghost">{SECRET}</p>'),
    (".ghost{color:#fff;background:#fff}", f'<p class="ghost">{SECRET}</p>'),
]
STILL_VISIBLE = [
    '<p style="display:block">KEPT</p>',
    '<p style="opacity:0.9">KEPT</p>',
    '<p style="font-size:10px">KEPT</p>',
    '<p style="height:20px">KEPT</p>',
    '<p style="margin-left:-10px">KEPT</p>',
    '<p style="background-color:transparent">KEPT</p>',
    '<p style="border-color:transparent">KEPT</p>',
    '<p style="color:#333;background:#fff">KEPT</p>',
    '<p style="color:#fff">KEPT</p>',
    '<p class="hiddenish">KEPT</p>',
    '<p aria-hidden="false">KEPT</p>',
    '<img hidden src="a.png"><p>KEPT</p>',
]


def page(element: str, style: str = "") -> str:
    return f"<html><head><style>{style}</style></head><body><p>{VISIBLE}</p>{element}</body></html>"


@pytest.mark.parametrize("element", HIDDEN_ELEMENTS)
def test_hidden_element_is_dropped(element: str) -> None:
    text = html_to_text(page(element)).text
    assert SECRET not in text
    assert VISIBLE in text


@pytest.mark.parametrize(("style", "element"), STYLESHEET_HIDDEN)
def test_stylesheet_hidden_element_is_dropped(style: str, element: str) -> None:
    extracted = html_to_text(page(element, style))
    assert SECRET not in extracted.text
    assert extracted.hidden_blocks == 1


@pytest.mark.parametrize("element", STILL_VISIBLE)
def test_visible_element_is_kept(element: str) -> None:
    assert "KEPT" in html_to_text(page(element)).text


def test_stylesheet_after_the_element_still_applies() -> None:
    html = (
        f'<body><p class="ghost">{SECRET}</p><p>{VISIBLE}</p><style>.ghost{{display:none}}</style>'
    )
    assert SECRET not in html_to_text(html).text


def test_text_matching_the_page_background_is_dropped() -> None:
    html = f'<body style="background:#fff"><p style="color:white">{SECRET}</p><p>{VISIBLE}</p>'
    assert SECRET not in html_to_text(html).text


def test_text_matching_a_stylesheet_page_background_is_dropped() -> None:
    style = "body{background:#000}"
    assert SECRET not in html_to_text(page(f'<p style="color:black">{SECRET}</p>', style)).text


def test_light_text_on_a_dark_page_is_kept() -> None:
    html = '<body style="background:#000"><p style="color:white">KEPT</p>'
    assert "KEPT" in html_to_text(html).text


def test_content_after_a_closed_hidden_element_is_kept() -> None:
    html = f"<div hidden><div>{SECRET}</div></div><p>{VISIBLE}</p>"
    assert VISIBLE in html_to_text(html).text


def test_unclosed_hidden_paragraph_ends_at_the_next_paragraph() -> None:
    html = f"<p hidden>{SECRET}<p>{VISIBLE}</p>"
    text = html_to_text(html).text
    assert SECRET not in text
    assert VISIBLE in text


def test_hidden_blocks_are_counted() -> None:
    html = f"<div hidden>{SECRET}</div><span hidden>{SECRET}</span><p>{VISIBLE}</p>"
    assert html_to_text(html).hidden_blocks == 2


def test_hidden_heading_is_not_used_as_the_page_heading() -> None:
    assert html_to_text(f"<h1 hidden>{SECRET}</h1><h2>Real</h2>").heading == "Real"
