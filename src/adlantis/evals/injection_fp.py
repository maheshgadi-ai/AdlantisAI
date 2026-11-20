"""Measures how often the injection detector flags ordinary web pages."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from adlantis.tools.untrusted import injection_matches, injection_signals

BENIGN_PAGES_PATH = Path(__file__).parent / "data" / "benign_pages.yaml"


class BenignPage(BaseModel):
    """A harmless page whose wording resembles an instruction."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^BP-\d{3}$")
    kind: str = Field(min_length=1)
    text: str = Field(min_length=1)


class BenignPageSet(BaseModel):
    """All benign pages."""

    model_config = ConfigDict(extra="forbid")

    pages: list[BenignPage]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> BenignPageSet:
        ids = [page.id for page in self.pages]
        if len(ids) != len(set(ids)):
            raise ValueError("page IDs must be unique")
        return self


class FlaggedPage(BaseModel):
    """A benign page the detector withheld, with the words that triggered it."""

    id: str
    kind: str
    matches: list[tuple[str, str]]


class FalsePositiveReport(BaseModel):
    """The detector's false-positive rate on a set of benign pages."""

    total: int
    flagged: list[FlaggedPage] = Field(default_factory=list)

    @property
    def rate(self) -> float:
        """The share of benign pages that were flagged."""
        return len(self.flagged) / self.total if self.total else 0.0


def load_benign_pages(path: Path = BENIGN_PAGES_PATH) -> BenignPageSet:
    """Read and validate the benign pages."""
    return BenignPageSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def measure_false_positives(pages: list[BenignPage]) -> FalsePositiveReport:
    """Run the detector over `pages`. This is offline and costs nothing."""
    flagged = [
        FlaggedPage(id=page.id, kind=page.kind, matches=injection_matches(page.text))
        for page in pages
        if injection_signals(page.text)
    ]
    return FalsePositiveReport(total=len(pages), flagged=flagged)
