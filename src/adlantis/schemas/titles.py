"""Clean up source titles that are really software metadata.

PDFs and office exports often carry a title set by the authoring tool, such as
"Microsoft Word - Final.docx", "PowerPoint Presentation", "Untitled", or a
" - Microsoft .NET" suffix. Those are useless as citation titles.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

_JUNK = re.compile(
    r"""^(?:
        untitled(?:\s+document)?(?:\s*\d+)? |
        (?:microsoft\s+)?(?:word|powerpoint|excel|office|\.net)(?:\s+document)? |
        microsoft\s+(?:word|powerpoint|excel)\s+-.* |
        powerpoint\s+presentation | presentation\s*\d* | slide\s*\d* |
        (?:adobe\s+)?(?:acrobat|indesign|photoshop|illustrator)(?:\s+\S+)* |
        (?:new\s+)?document\s*\d* | no\s+title | title | unknown | none | null | n/a |
        [^/\\]*\.(?:docx?|pptx?|xlsx?|pdf|indd|rtf|odt|tex|html?) |
        pdf | doc | ppt
    )$""",
    re.IGNORECASE | re.VERBOSE,
)
UNTITLED_PREFIX = "Untitled document ("
_FILE_TAG = re.compile(
    r"^(?:[\[(](?:pdf|html?|docx?|pptx?|xlsx?|txt)[\])]|(?:pdf|html?):)\s*", re.I
)
_DANGLING = frozenset("a an and as at but by for from in into of on or the to with via vs".split())  # noqa: SIM905
# Site or publisher names that search results append to the real title.
_PUBLISHER = re.compile(
    r"""^(?:
        sciencedirect(?:\.com)? | springer(?:link|\s+nature(?:\s+link)?)? |
        wiley(?:\s+online\s+library)? |
        taylor\s+&\s+francis(?:\s+online)? | iopscience | mdpi | nature | nature\.com | pubmed |
        pmc | ncbi | pubmed\s+central | researchgate | arxiv(?:\.org)? | ieee\s+xplore |
        acs\s+publications | rsc\s+publishing | pubs\.rsc\.org | frontiers | sciencedaily |
        oxford\s+academic | cambridge\s+core | sage\s+journals | plos(?:\s+one)? |
        wikipedia | youtube | medium | linkedin | semantic\s+scholar | google\s+scholar
    )$""",
    re.IGNORECASE | re.VERBOSE,
)
# Spaced separators only (hyphen, en dash, em dash, bar), so "e-bike" stays intact.
_SEPARATORS = re.compile(r"\s+[-\u2013\u2014|]\s+")
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=\d)")


def tidy_title(title: str) -> str:
    """Normalize a title: whitespace, file-type tags, and truncation leftovers.

    - "[PDF] Solid-State Li-Metal Batteries" → "Solid-State Li-Metal Batteries";
    - "Solid-State Batteries: The Technology of the 2030s but the ..." → "Solid-State
      Batteries: The Technology of the 2030s" (ellipsis and dangling words removed).
    """
    title = " ".join(title.split())
    title = _FILE_TAG.sub("", title)
    truncated = re.search(r"(?:\.{3,}|\u2026)\s*$", title) is not None
    title = re.sub(r"(?:\s*(?:\.{3,}|\u2026))+$", "", title).rstrip(" -\u2013\u2014|:;,")
    if truncated:
        words = title.split()
        while len(words) > 3 and words[-1].lower().strip(",;:") in _DANGLING:
            words.pop()
        title = " ".join(words).rstrip(" -\u2013\u2014|:;,")
    return title


def is_untitled(title: str) -> bool:
    """True for the placeholder `clean_title` produces when nothing better exists."""
    return title.startswith(UNTITLED_PREFIX)


def is_junk_title(title: str) -> bool:
    """True when the title is empty or only authoring-software metadata."""
    parts = [p.strip() for p in _SEPARATORS.split(title.strip()) if p.strip()]
    return not parts or all(_JUNK.match(p) for p in parts)


def clean_title(title: str, url: str, heading: str | None = None, text: str | None = None) -> str:
    """A usable title: junk and publisher segments removed; otherwise the first heading,
    a title-like first line of the text, a readable file name, or "Untitled document (host)".

    "Batteries and Secure Energy Transitions - Microsoft .NET" keeps its real part,
    "Advances in X - ScienceDirect" drops the trailing publisher name;
    "Microsoft Word - draft.docx" falls back to the page heading or the URL's file name.
    """
    title = tidy_title(title)
    if title and title != url:
        kept = [p.strip() for p in _SEPARATORS.split(title) if p.strip()]
        kept = [p for p in kept if not _JUNK.match(p)]
        while len(kept) > 1 and _PUBLISHER.match(kept[-1]):  # "Title - ScienceDirect"
            kept.pop()
        if kept:
            return " - ".join(kept)
    if heading and not is_junk_title(heading):
        return tidy_title(heading)
    first_line = _title_like_first_line(text or "")
    if first_line:
        return first_line
    from_url = title_from_url(url)
    if from_url:
        return from_url
    host = (urlsplit(url).hostname or url).removeprefix("www.")
    return f"{UNTITLED_PREFIX}{host})"


def title_from_url(url: str) -> str:
    """Readable title from a URL's file name ("GlobalEVOutlook2025.pdf" → "Global EV Outlook 2025").

    Returns the host for a site's home page, and "" when the last path segment isn't
    word-like (an id or hash such as "NL21V7636.pdf").
    """
    parts = urlsplit(url)
    segment = unquote(parts.path.rstrip("/").rsplit("/", 1)[-1])
    if not segment:
        return (parts.hostname or "").removeprefix("www.")
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", segment)
    words = _CAMEL.sub(" ", re.sub(r"[-_+.]+", " ", stem)).split()
    if re.search(r"[A-Za-z]{3,}", stem) and words:
        return " ".join(words)
    return ""


def _title_like_first_line(text: str) -> str:
    """The text's first line if it reads like a title (3-20 words, no final period)."""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = tidy_title(line)
    words = line.split()
    if not 3 <= len(words) <= 20 or len(line) > 150 or line.endswith("."):
        return ""
    if not re.match(r"[A-Za-z]", line) or is_junk_title(line):
        return ""
    return line
