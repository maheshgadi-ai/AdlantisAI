"""Finds what a sentence rules out, so "no logos" is not read as a request for logos."""

from __future__ import annotations

import re

_TOKEN = re.compile("[\\w'\u2019-]+|\\n|[^\\w\\s]")
_NEGATORS = frozenset(
    {"no", "not", "without", "never", "avoid", "avoids", "avoiding"}
    | {"exclude", "excludes", "excluding", "omit", "omits", "omitting"}
)
_NOT_A_NEGATION = frozenset({"only", "just", "merely", "without", "omit", "omitting", "exclude"})
_LEADERS = frozenset(
    {"any", "visible", "readable", "recognizable", "identifiable", "show", "shows", "showing"}
    | {"display", "displaying", "include", "including", "depict", "depicting", "feature"}
    | {"featuring", "contain", "containing", "use", "using", "have", "having"}
)
_ENDS_ITEM = frozenset(
    {"a", "an", "the", "our", "their", "your", "my", "his", "her", "this", "that", "these"}
    | {"those", "with", "on", "in", "at", "of", "over", "above", "under", "beside", "across"}
    | {"but", "except", "only", "than", "more", "less", "fewer", "other", "is", "are", "was"}
    | {"were", "be", "has", "have", "shows", "show", "which", "who", "while", "where", "when"}
    | {"hide", "hides", "remove", "removes", "forget", "skip", "lose", "drop", "miss", "lack"}
    | {"blur", "obscure", "cover", "crop", "omit", "exclude", "for", "from", "to", "by", "as"}
    | {"and", "or", "nor"}
    | _NEGATORS
)
_SEPARATORS = frozenset({",", "/", "or", "and", "nor"})
_SENTENCE_ENDS = frozenset({".", ";", ":", "!", "?", "\n"})
_NOUNS_IN_ING = frozenset({"branding", "packaging", "lettering", "clothing", "writing", "labeling"})
_MAX_ITEM_WORDS = 4


def _item_word(word: str) -> bool:
    lower = word.lower()
    if lower in _ENDS_ITEM or not any(char.isalnum() for char in lower):
        return False
    return not lower.endswith("ing") or lower in _NOUNS_IN_ING


def _skip_leaders(words: list[str], index: int) -> int:
    while index < len(words) and words[index].lower() in _LEADERS:
        index += 1
    return index


def _negated_end(words: list[str], start: int) -> int:
    """The index just past the list of things ruled out, or `start` when there is none."""
    index, end, first = start, start, True
    while True:
        index = _skip_leaders(words, index)
        stop = index
        while stop < len(words) and stop - index < _MAX_ITEM_WORDS and _item_word(words[stop]):
            stop += 1
        if stop == index:
            return end
        following = words[stop].lower() if stop < len(words) else "."
        if following in _SEPARATORS:
            end, index, first = stop, stop + 1, False
            while index < len(words) and words[index].lower() in _SEPARATORS:
                index += 1
        elif following in _SENTENCE_ENDS or first:
            return stop
        else:  # a later item that runs on is a new statement: "no text and logo on the cup"
            return end


def without_negated(text: str) -> str:
    """The text with every ruled-out list removed. Anything uncertain is left in place."""
    tokens = list(_TOKEN.finditer(text))
    words = [token.group() for token in tokens]
    pieces: list[str] = []
    position, index = 0, 0
    while index < len(tokens):
        lower = words[index].lower()
        free_of = (
            lower == "free"
            and index + 1 < len(words)
            and words[index + 1].lower()
            in {
                "of",
                "from",
            }
        )
        following = words[index + 1].lower() if index + 1 < len(words) else ""
        if lower in _NEGATORS and following in _NOT_A_NEGATION:
            index += 2  # "not only" and "do not omit" rule nothing out
            continue
        if free_of or lower in _NEGATORS:
            start = index + (2 if free_of else 1)
            end = _negated_end(words, start)
            if end > start:
                pieces.append(text[position : tokens[index].start()])
                position = tokens[end - 1].end()
                index = end
                continue
        index += 1
    pieces.append(text[position:])
    return re.sub(r"(?<![\w-])[\w-]+-free(?![\w-])", " ", "".join(pieces))
