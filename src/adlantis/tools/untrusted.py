"""Handling for text from the web, which is always data and never instructions.

Detection here is one layer. The stronger guarantees are structural: research output cannot
express a change to facts, only URLs from search results can be read, and every finding must
quote its source. Those hold even when a manipulative sentence is not recognized.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from adlantis.schemas.evidence_store import EvidenceRecord
from adlantis.schemas.research import ResearchFinding

BOUNDARY_TAG = "untrusted_web_content"
_KEEP_CONTROLS = {"\n", "\t"}
_AI = r"(?:ai|llms?|language\s+models?|chatbots?|bots?|crawlers?)"
_REVIEWER = r"(?:user|human|operator|reviewer)"

INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "override",
        r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:(?:all|any|the|your|my|these|those)\s+)*"
        r"(?:previous|prior|above|earlier|preceding|system|developer)\s+"
        r"(?:instructions?|prompts?|directions?|guidelines?|rules?|messages?)\b",
    ),
    (
        "override",
        r"\b(?:ignore|disregard|override|bypass)\s+(?:(?:all|any|your|my)\s+)+(?:instructions?|prompts?)\b",
    ),
    (
        "role_change",
        r"\byou\s+are\s+now\s+(?:an?\s+|the\s+|in\s+)?"
        r"(?:admin|administrator|developer|system|root|unrestricted|jailbroken|debug)\b",
    ),
    ("new_instructions", r"\b(?:new|updated|revised)\s+(?:system\s+)?instructions?\s*:"),
    (
        "new_instructions",
        r"\bfollow\s+(?:these|the\s+following|my)\s+(?:new|updated|revised)\s+instructions\b",
    ),
    ("prompt_reference", r"\b(?:system\s+prompt|developer\s+message)\b"),
    ("role_label", r"^\s*(?:system|assistant|developer)\s*:"),
    ("chat_markup", r"<\|[a-z_]+\|>"),
    ("chat_markup", r"\[/?inst\]"),
    ("chat_markup", r"<</?sys>>"),
    (
        "chat_markup",
        r"</?(?:system|assistant|tool_call|function_call|untrusted_web_content)\b[^>]*>",
    ),
    (
        "addresses_ai",
        r"\b(?:attention|note|message|instructions?)\s+(?:to|for)\s+(?:the\s+|any\s+|all\s+)?"
        + _AI
        + r"\b",
    ),
    (
        "addresses_ai",
        r"\b(?:if|when)\s+you\s+are\s+an?\s+(?:ai|llm|language\s+model|bot|automated\s+agent)\b",
    ),
    ("addresses_ai", r"\bdear\s+(?:ai|llm|assistant|chatbot|language\s+model)\b"),
    (
        "fact_tampering",
        r"\b(?:change|update|modify|edit|replace|rewrite|alter|overwrite)\s+"
        r"(?:the\s+|your\s+|this\s+|our\s+|their\s+)?"
        r"(?:fact\s+sheet|facts?\.ya?ml|brand\s+facts?|approved\s+(?:facts?|claims?)"
        r"|banned\s+(?:words?|claims?)|claims?\s+appendix)\b",
    ),
    (
        "fact_tampering",
        r"\badd\s+(?:\w+\s+){0,4}?to\s+(?:the\s+|your\s+)?(?:fact\s+sheet|approved\s+(?:facts?|claims?))\b",
    ),
    (
        "fact_tampering",
        r"\b(?:add|record|include|save|store)\s+(?:this|these|that|it)\s+as\s+(?:an?\s+)?"
        r"(?:approved|verified|supported|new)\s+(?:facts?|claims?)\b",
    ),
    (
        "fact_tampering",
        r"\b(?:brand|product)(?:'s)?\s+(?:facts?|claims?)\s+(?:should|must)\s+(?:now\s+)?"
        r"(?:say|state|read|be\s+changed)\b",
    ),
    (
        "verdict_tampering",
        r"\b(?:mark|treat|record|report|classify|label)\s+(?:\w+\s+){0,4}?(?:claims?|facts?|statements?)"
        r"\s+as\s+(?:approved|supported|verified|true|trusted)\b",
    ),
    (
        "verdict_tampering",
        r"\b(?:mark|treat|rate|score|rank|classify|label)\s+(?:this|the)\s+(?:page|source|site|article)"
        r"\s+as\s+(?:approved|trusted|authoritative|high[\s-]quality|verified)\b",
    ),
    (
        "verdict_tampering",
        r"\b(?:automatically|immediately|please|you\s+must)\s+approve\s+(?:this|the)\s+(?:kit|campaign|claims?)\b",
    ),
    (
        "forced_wording",
        r"\b(?:you\s+must|be\s+sure\s+to|make\s+sure\s+to)\s+(?:say|claim|state|write)\s+that\b",
    ),
    (
        "exfiltration",
        r"\b(?:reveal|print|show|repeat|leak|output|exfiltrate)\s+(?:me\s+)?(?:your|the)\s+"
        r"(?:hidden\s+instructions|api\s+keys?|credentials|environment\s+variables?)\b",
    ),
    ("exfiltration", r"\b(?:send|post|forward|upload)\s+(?:\w+\s+){0,4}?to\s+https?://"),
    ("tool_direction", r"\b(?:call|use|invoke|run)\s+the\s+(?:fetch_url|web_search)\s+tool\b"),
    ("tool_direction", r"\bfetch\s+https?://"),
    ("concealment", r"\bdo\s+not\s+(?:tell|inform)\s+the\s+" + _REVIEWER + r"\b"),
    ("concealment", r"\bwithout\s+telling\s+the\s+" + _REVIEWER + r"\b"),
)
_COMPILED = tuple(
    (name, re.compile(pattern, re.IGNORECASE | re.MULTILINE))
    for name, pattern in INJECTION_PATTERNS
)
# Catches instructions spelled with separators, such as "i g n o r e  p r e v i o u s".
_SQUEEZED = re.compile(
    r"(?:ignore|disregard|forget|override)(?:all|any|the|your|my)*"
    r"(?:previous|prior|above|earlier|preceding)(?:instructions?|prompts?)"
)


def sanitize(text: str) -> str:
    """Fold compatibility forms and remove invisible and control characters."""
    folded = unicodedata.normalize("NFKC", text)
    return "".join(
        char
        for char in folded
        if char in _KEEP_CONTROLS or unicodedata.category(char) not in {"Cc", "Cf", "Co", "Cs"}
    )


def injection_signals(text: str) -> tuple[str, ...]:
    """Names of the manipulation patterns found in `text`, in a stable order."""
    clean = sanitize(text)
    found = {name for name, pattern in _COMPILED if pattern.search(clean)}
    if _SQUEEZED.search(re.sub(r"[\W_]+", "", clean).lower()):
        found.add("override")
    return tuple(sorted(found))


def injection_matches(text: str) -> list[tuple[str, str]]:
    """Each detector name with the passage that triggered it, for audit reports."""
    clean = sanitize(text)
    return [
        (name, match.group())
        for name, pattern in _COMPILED
        if (match := pattern.search(clean)) is not None
    ]


def quote_appears_in(quote: str, text: str) -> bool:
    """True when `quote` occurs in `text`, ignoring case and spacing."""
    return _comparable(quote) in _comparable(text)


def _comparable(text: str) -> str:
    return " ".join(sanitize(text).split()).casefold()


def render_untrusted(records: Iterable[EvidenceRecord], nonce: str) -> str:
    """Wrap usable records in a boundary a page cannot forge. Quarantined text is never shown."""
    blocks = [
        f"[{record.id}] {record.title}\nurl: {record.url}\n"
        f"source quality: {record.rating.tag()}\nexcerpt:\n{record.excerpt}"
        for record in records
        if record.status == "usable"
    ]
    body = "\n\n".join(blocks)
    return f'<{BOUNDARY_TAG} boundary="{nonce}">\n{body}\n</{BOUNDARY_TAG} boundary="{nonce}">'


def render_findings(findings: Iterable[ResearchFinding], nonce: str) -> str:
    """Wrap research findings, which derive from web text, in the same unforgeable boundary."""
    blocks = [
        f"[{', '.join(finding.evidence_ids)}] ({finding.kind}) {finding.statement}\n"
        f"source passage: {finding.supporting_quote}"
        for finding in findings
    ]
    body = "\n\n".join(blocks)
    return f'<{BOUNDARY_TAG} boundary="{nonce}">\n{body}\n</{BOUNDARY_TAG} boundary="{nonce}">'
