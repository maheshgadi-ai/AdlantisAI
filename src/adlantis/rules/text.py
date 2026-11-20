"""Text handling for the rules: normalization, matching, and span arithmetic."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

_INVISIBLE = (0x00AD, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF)
_LOOKALIKES = {
    0x2018: "'",
    0x2019: "'",
    0x201C: '"',
    0x201D: '"',
    0x2010: "-",
    0x2011: "-",
    0x2012: "-",
    0x2013: "-",
    0x2014: "-",
    0x2212: "-",
}
_TABLE = {**dict.fromkeys(_INVISIBLE), **_LOOKALIKES}
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*")
REFERENCE_ID = re.compile(r"\b[FE]-\d+\b")
_INVITATIONS = frozenset(
    {"meet", "try", "order", "shop", "buy", "get", "discover", "explore", "introducing", "see"}
    | {"the", "our"}
)
_EDGE_PUNCTUATION = ".,:;!?-\"'()"


@dataclass(frozen=True)
class Hit:
    """A matched span of normalized text."""

    start: int
    end: int
    quote: str


def normalize(text: str) -> str:
    """Fold compatibility forms, remove invisible characters, and unify quotes and dashes."""
    return unicodedata.normalize("NFKC", text).translate(_TABLE)


def bounded(patterns: Iterable[str]) -> re.Pattern[str]:
    """Compile patterns into one case-insensitive matcher on word boundaries."""
    return re.compile(rf"(?<!\w)(?:{'|'.join(patterns)})(?!\w)", re.IGNORECASE)


def phrase_pattern(phrase: str) -> str:
    """A regex for `phrase` that tolerates any spacing or hyphen between its words."""
    words = re.split(r"[\s-]+", normalize(phrase).strip())
    return r"[\s-]*".join(re.escape(word) for word in words)


def find_hits(patterns: Iterable[re.Pattern[str]], text: str) -> list[Hit]:
    """All matches in reading order, dropping any match contained in a longer one."""
    spans = sorted(
        {(m.start(), m.end()) for pattern in patterns for m in pattern.finditer(text)},
        key=lambda span: (span[0], span[0] - span[1]),
    )
    kept: list[tuple[int, int]] = []
    for start, end in spans:
        if not any(a <= start and end <= b for a, b in kept):
            kept.append((start, end))
    return [Hit(start, end, text[start:end]) for start, end in kept]


def wording_spans(wordings: Iterable[str], text: str) -> list[tuple[int, int]]:
    """Where any approved wording appears verbatim, ignoring case and spacing."""
    spans: list[tuple[int, int]] = []
    for wording in wordings:
        words = normalize(wording).split()
        pattern = r"\s+".join(re.escape(word) for word in words)
        spans += [m.span() for m in re.finditer(rf"(?<!\w){pattern}(?!\w)", text, re.IGNORECASE)]
    return spans


def is_inside(hit: Hit, spans: Iterable[tuple[int, int]]) -> bool:
    """True when the hit lies entirely within one of the spans."""
    return any(start <= hit.start and hit.end <= end for start, end in spans)


def fold(text: str) -> str:
    """A comparable form of text: normalized, single-spaced, and case-folded."""
    return " ".join(normalize(text).split()).casefold()


def contains_text(haystack: str, needle: str) -> bool:
    """True when `needle` has content and occurs in `haystack`, ignoring case and spacing."""
    wanted = fold(needle)
    return bool(wanted) and wanted in fold(haystack)


def names_only(text: str, names: Iterable[str]) -> bool:
    """True when `text` is just a name, alone or after an invitation such as "Meet"."""
    remainder = fold(text)
    found = False
    for name in sorted({fold(name) for name in names if name.strip()}, key=len, reverse=True):
        remainder, count = re.subn(rf"(?<!\w){re.escape(name)}(?!\w)", " ", remainder)
        found = found or count > 0
    words = {word.strip(_EDGE_PUNCTUATION) for word in remainder.split()} - {""}
    return found and words <= _INVITATIONS


def sentences(text: str) -> list[tuple[int, str]]:
    """Each sentence with its offset in `text`."""
    return [(m.start(), m.group()) for m in _SENTENCE.finditer(text)]
