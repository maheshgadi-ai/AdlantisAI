"""Wording that signals pricing, testimonial, statistic, comparison, or disparaging claims.

Each pattern sits on its own line, and each has a test proving it fires.
"""

from __future__ import annotations

import re

from adlantis.rules.text import bounded

MONEY = bounded(
    (
        r"[$€£]\s?\d[\d,]*(?:\.\d{1,2})?",
        r"\d[\d,]*(?:\.\d{1,2})?\s?(?:dollars|bucks|usd|eur|euros|gbp)",
    )
)

PRICING_TERMS = bounded(
    (
        r"free\s+(?:shipping|delivery|returns?|trial)",
        r"for\s+free",
        r"\d+(?:\.\d+)?\s?(?:%|percent)\s+off",
        r"save\s+\d+(?:\.\d+)?\s?(?:%|percent)",
        r"half[\s-]price",
        r"discount(?:s|ed)?",
        r"on\s+sale",
        r"sale\s+price",
        r"lowest\s+prices?",
        r"best\s+prices?",
        r"price[\s-](?:match|guarantee)",
        r"money[\s-]back",
        r"no\s+hidden\s+fees",
        r"0\s?%\s+(?:apr|interest)",
        r"interest[\s-]free",
        r"financing",
        r"pay\s+in\s+\d+",
        r"buy\s+one,?\s+get\s+one",
        r"bogo",
        r"limited[\s-]time\s+offer",
    )
)

TESTIMONIAL_TERMS = bounded(
    (
        r"customers?\s+(?:say|says|agree|agrees|love|loves|rave|raves|swear|swears|rate|rates)",
        r"(?:rated|rating\s+of)\s+\d(?:\.\d)?\s+out\s+of\s+5",
        r"\d(?:\.\d)?[\s-]stars?",
        r"five[\s-]stars?",
        r"as\s+seen\s+(?:in|on)",
        r"featured\s+(?:in|on)",
        r"endorsed\s+by",
        r"recommended\s+by",
        r"approved\s+by",
        r"trusted\s+by",
        r"loved\s+by",
        r"chosen\s+by",
        r"used\s+by\s+(?:\w+\s+)?(?:pros|professionals|thousands|millions|athletes|baristas|experts)",
        r"(?:doctors|experts|baristas|dentists|athletes|riders|chefs|cyclists)"
        r"\s+(?:agree|recommend|choose|prefer|love|trust)",
        r"(?:happy|satisfied)\s+customers",
        r"testimonials?",
        r"reviewers?\s+(?:say|says|call|calls)",
        r"rave\s+reviews",
        r"verified\s+(?:buyer|purchase|review)",
    )
)

# Case-sensitive: a capitalized name is what makes these attributions.
ATTRIBUTED_QUOTE = re.compile(
    r"\"[^\"\n]{3,240}\"\s*(?:-|,|said|says)\s*[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)*"
)
NAMED_SPEAKER = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]*\.?\s+(?:says|said|swears)\b")

STATISTIC = bounded(
    (
        r"\d+(?:\.\d+)?\s?(?:%|percent)",
        r"\d+\s+(?:out\s+of|in)\s+\d+",
        r"\d+(?:\.\d+)?x",
        r"\d+(?:\.\d+)?\s+times",
        r"\d+(?:\.\d+)?\s+(?:million|billion)",
    )
)

COMPARISON = bounded(
    (
        r"(?!(?:other|rather|earlier|later|sooner)\b)\w+er\s+than(?!\s+ever\b)",
        r"(?:more|less)\s+\w+\s+than",
        r"compared\s+(?:to|with)",
        r"versus",
        r"vs\.?",
        r"outperforms?",
        r"outlasts?",
    )
)

DISPARAGING = bounded(
    (
        r"worse",
        r"inferior",
        r"bad",
        r"poor(?:ly)?",
        r"weak(?:er)?",
        r"overpriced",
        r"cheap",
        r"rip[\s-]?off",
        r"scam(?:s|my)?",
        r"fake",
        r"unreliable",
        r"flimsy",
        r"stale",
        r"burnt",
        r"bland",
        r"terrible",
        r"awful",
        r"mediocre",
        r"outdated",
        r"fails?",
        r"lags?",
        r"beats?",
        r"crushes",
        r"destroys?",
        r"superior\s+to",
        r"outperforms?",
        r"(?!(?:other|rather|earlier|later|sooner)\b)\w+er\s+than",
        r"more\s+\w+\s+than",
        r"unlike",
        r"instead\s+of",
        r"ditch",
        r"forget",
        r"can'?t\s+match",
        r"no\s+match\s+for",
    )
)

GENERIC_DISPARAGEMENT = bounded(
    (
        r"unlike\s+(?:our\s+|the\s+)?(?:competitors?|rivals?|competition|other\s+brands|big\s+brands)",
        r"(?:competitors?|rivals?|the\s+competition|other\s+brands)"
        r"\s+(?:can'?t|cannot|fail|fails|cut\s+corners|skimp|overcharge)",
    )
)
