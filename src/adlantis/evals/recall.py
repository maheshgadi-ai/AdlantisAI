"""Measures how many hand-labeled claims the claim checker finds."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pydantic import BaseModel, Field

from adlantis.evals.claim_labels import LabeledSnippet
from adlantis.rules.text import contains_text, fold
from adlantis.schemas.claim_check import CheckedClaim

MIN_WORD_OVERLAP = 0.6
Extract = Callable[[LabeledSnippet], Sequence[CheckedClaim]]


class RecallReport(BaseModel):
    """Claim-extraction results over the labeled set."""

    snippets: int = 0
    labeled_claims: int = 0
    found: int = 0
    correct_type: int = 0
    clean_snippets: int = 0
    over_extracted: int = 0
    failed_snippets: int = 0
    cost_usd: float = 0.0
    missed: list[str] = Field(default_factory=list)

    @property
    def recall(self) -> float:
        """The share of labeled claims that were found."""
        return self.found / self.labeled_claims if self.labeled_claims else 0.0

    @property
    def type_accuracy(self) -> float:
        """The share of found claims given the labeled type."""
        return self.correct_type / self.found if self.found else 0.0


def same_claim(label: str, extracted: str) -> bool:
    """True when an extracted quote states the labeled claim."""
    if contains_text(extracted, label) or contains_text(label, extracted):
        return True
    first, second = set(fold(label).split()), set(fold(extracted).split())
    return len(first & second) / len(first | second) >= MIN_WORD_OVERLAP


def score_recall(snippets: Sequence[LabeledSnippet], extract: Extract) -> RecallReport:
    """Run extraction over every snippet. A snippet that fails counts its claims as missed."""
    report = RecallReport(snippets=len(snippets))
    for snippet in snippets:
        report.labeled_claims += len(snippet.claims)
        try:
            extracted = list(extract(snippet))
        except RuntimeError:
            report.failed_snippets += 1
            report.missed += [f"{snippet.id}: {claim.quote}" for claim in snippet.claims]
            continue
        if not snippet.claims:
            report.clean_snippets += 1
            report.over_extracted += bool(extracted)
        for label in snippet.claims:
            match = next((c for c in extracted if same_claim(label.quote, c.quote)), None)
            if match is None:
                report.missed.append(f"{snippet.id}: {label.quote}")
                continue
            report.found += 1
            report.correct_type += match.claim_type == label.claim_type
    return report
