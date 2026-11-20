"""Readable-text extraction from HTML using only the standard library.

Drops scripts, styles, navigation, and other page chrome; keeps headings, paragraphs,
and list items as separate lines. When the page marks up its main content
(`<main>` or `<article>`) and it has substance, only that part is returned.

Text a reader cannot see is dropped too, because hidden text is a common way to plant
instructions for automated readers. Without a browser this is best effort, so the text
that remains is still treated as untrusted.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import NamedTuple

_SKIP = {
    "script", "style", "noscript", "template", "svg", "canvas", "iframe", "object",
    "nav", "header", "footer", "aside", "form", "button", "select", "textarea", "dialog",
}  # fmt: skip
_BLOCK = {
    "p", "div", "section", "article", "main", "li", "ul", "ol", "table", "tr", "td", "th",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "dd", "dt", "figcaption", "br", "hr",
}  # fmt: skip
_MAIN = {"main", "article"}
_HEADINGS = {"h1", "h2", "h3"}
_MIN_MAIN_CHARS = 200
_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
    "track", "wbr",
}  # fmt: skip
_AUTO_CLOSING = {"p", "li", "dt", "dd", "tr", "td", "th"}
_HIDDEN_CLASSES = {
    "sr-only", "visually-hidden", "visuallyhidden", "screen-reader-text", "hidden", "d-none",
    "invisible",
}  # fmt: skip
_END = r"\s*(?:;|$|!)"
HIDDEN_STYLES = (
    r"display\s*:\s*none",
    r"visibility\s*:\s*(?:hidden|collapse)",
    r"opacity\s*:\s*0(?:\.0+)?" + _END,
    r"font-size\s*:\s*0(?:\.0+)?(?:px|em|rem|pt|%)?" + _END,
    r"(?:max-)?(?:height|width)\s*:\s*0(?:px)?" + _END,
    r"text-indent\s*:\s*-\d{3,}",
    r"(?<![\w-])(?:left|top|right|bottom|margin-left|margin-top)\s*:\s*-\d{3,}",
    r"clip\s*:\s*rect\(\s*0",
    r"clip-path\s*:\s*inset\(\s*(?:50|100)%",
    r"transform\s*:\s*scale\(\s*0(?:\.0+)?\s*\)",
    r"(?<![\w-])color\s*:\s*transparent",
)
_HIDDEN_STYLE = re.compile("|".join(HIDDEN_STYLES), re.IGNORECASE)
_STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.IGNORECASE | re.DOTALL)
_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_SIMPLE_SELECTOR = re.compile(r"^[a-z0-9]*([.#])([\w-]+)$", re.IGNORECASE)
_TEXT_COLOR = re.compile(r"(?<![\w-])color\s*:\s*([^;!}]+)", re.IGNORECASE)
_BACKGROUND = re.compile(r"background(?:-color)?\s*:\s*([^;!}]+)", re.IGNORECASE)
_WHITE = {"white", "#fff", "#ffffff", "rgb(255,255,255)"}
_BLACK = {"black", "#000", "#000000", "rgb(0,0,0)"}


class ExtractedPage(NamedTuple):
    """Readable parts of an HTML page."""

    title: str  # contents of <title>, whitespace-collapsed
    text: str  # readable body text, one block per line
    heading: str  # first visible h1-h3, a fallback when the title is junk
    hidden_blocks: int = 0  # elements dropped because a reader could not see them


def _color(value: str) -> str:
    name = "".join(value.lower().split())
    return "white" if name in _WHITE else "black" if name in _BLACK else name


def _matches_background(style: str, page_background: str | None) -> bool:
    """True when text is drawn in the same color as whatever is behind it."""
    text = _TEXT_COLOR.search(style)
    if text is None:
        return False
    background = _BACKGROUND.search(style)
    behind = _color(background.group(1)) if background else page_background
    return behind is not None and _color(text.group(1)) == behind


def _hidden_selectors(html: str) -> tuple[set[str], set[str], str | None]:
    """Classes and IDs that stylesheets hide, plus the page background color."""
    classes, ids = set(_HIDDEN_CLASSES), set()
    page_background = None
    for sheet in _STYLE_BLOCK.findall(html):
        for selectors, body in _CSS_RULE.findall(sheet):
            names = [s.strip() for s in selectors.split(",")]
            if "body" in names and (background := _BACKGROUND.search(body)):
                page_background = _color(background.group(1))
            if not (_HIDDEN_STYLE.search(body) or _matches_background(body, None)):
                continue
            for name in names:
                if match := _SIMPLE_SELECTOR.match(name):
                    (classes if match[1] == "." else ids).add(match[2])
    return classes, ids, page_background


class _Extractor(HTMLParser):
    def __init__(self, html: str = "", *, keep_forms: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self._skipped = _SKIP - {"form"} if keep_forms else _SKIP
        self._hidden_classes, self._hidden_ids, self._page_background = _hidden_selectors(html)
        self._hidden_tag: str | None = None
        self._hidden_depth = 0
        self.hidden_blocks = 0
        self.title = ""
        self._in_title = False
        self.heading = ""
        self._in_heading = False
        self._skip_depth = 0
        self._main_depth = 0
        self.all_parts: list[str] = []
        self.main_parts: list[str] = []

    def _is_hidden(self, attrs: list[tuple[str, str | None]]) -> bool:
        values = {name: value or "" for name, value in attrs}
        style = values.get("style", "")
        return (
            "hidden" in values
            or values.get("aria-hidden", "").lower() == "true"
            or _HIDDEN_STYLE.search(style) is not None
            or _matches_background(style, self._page_background)
            or bool(self._hidden_classes & set(values.get("class", "").split()))
            or values.get("id", "") in self._hidden_ids
        )

    def _track_hidden_start(self, tag: str) -> bool:
        """Follow nesting inside a hidden element. True while the new tag stays hidden."""
        if tag == self._hidden_tag:
            if tag in _AUTO_CLOSING:  # a new <p> ends an unclosed hidden <p>
                self._hidden_tag = None
                return False
            self._hidden_depth += 1
        return True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            style = dict(attrs).get("style") or ""
            if background := _BACKGROUND.search(style):
                self._page_background = _color(background.group(1))
        if self._hidden_tag and self._track_hidden_start(tag):
            return
        if tag not in _VOID and self._is_hidden(attrs):
            self._hidden_tag, self._hidden_depth = tag, 1
            self.hidden_blocks += 1
            return
        if tag in self._skipped:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _HEADINGS and not self.heading.strip() and not self._skip_depth:
            self._in_heading = True
        if tag in _MAIN:
            self._main_depth += 1
        if tag in _BLOCK:
            self._emit("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._hidden_tag:
            if tag == self._hidden_tag:
                self._hidden_depth -= 1
                if self._hidden_depth == 0:
                    self._hidden_tag = None
            return
        if tag in self._skipped and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _HEADINGS:
            self._in_heading = False
        if tag in _MAIN and self._main_depth:
            self._main_depth -= 1
        if tag in _BLOCK:
            self._emit("\n")

    def handle_data(self, data: str) -> None:
        if self._hidden_tag:
            return
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            if self._in_heading:
                self.heading += data
            self._emit(data)

    def _emit(self, text: str) -> None:
        self.all_parts.append(text)
        if self._main_depth:
            self.main_parts.append(text)


def html_to_text(html: str) -> ExtractedPage:
    """Return the title, readable text, and first heading of an HTML document.

    Forms are page chrome, except on sites that wrap the whole page in one. Their content is
    read only when the page has almost no text outside its forms.
    """
    page = _extract(html, keep_forms=False)
    if len(page.text) < _MIN_MAIN_CHARS and "<form" in html.lower():
        return _extract(html, keep_forms=True)
    return page


def _extract(html: str, *, keep_forms: bool) -> ExtractedPage:
    parser = _Extractor(html, keep_forms=keep_forms)
    parser.feed(html)
    parser.close()
    main = _tidy("".join(parser.main_parts))
    text = main if len(main) >= _MIN_MAIN_CHARS else _tidy("".join(parser.all_parts))
    return ExtractedPage(
        " ".join(parser.title.split()), text, " ".join(parser.heading.split()), parser.hidden_blocks
    )


def _tidy(text: str) -> str:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)
