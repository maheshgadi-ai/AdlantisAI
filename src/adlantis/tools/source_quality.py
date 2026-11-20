"""Configurable source-quality scorer: domain allow/deny rules with weights.

Rules come from YAML (`config/source_quality.yaml` by default, or
`SOURCE_QUALITY_PATH`). For a URL's host, the first match wins in this order:
1. `deny`: domain suffixes rated 0 ("blocked"), e.g. known content farms;
2. `domains`: specific domains with a score and label (the longest match wins, so
   `pmc.ncbi.nlm.nih.gov` beats `nih.gov`);
3. `suffixes`: host endings such as `.edu`, `.gov`, `.ac.uk`;
4. `default`.

Scores map to tiers through `tiers` thresholds, except that a URL matching no rule
is `unrated` (with the neutral default score): an unknown publisher is not evidence
of a weak one. This is a heuristic about *where*
a source is published, not a judgment of each page; it is recorded on each evidence
record so strategy and copy can weigh sources, and it feeds the evals.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, Field

from adlantis.config.models import CONFIG_DIR, ConfigurationError
from adlantis.schemas.quality import QualityTier, SourceRating

DEFAULT_SOURCE_QUALITY_PATH = CONFIG_DIR / "source_quality.yaml"


class DomainRule(BaseModel):
    """A weight (0-1) and a label for a domain or host suffix."""

    score: float = Field(ge=0.0, le=1.0)
    label: str


class TierThresholds(BaseModel):
    """Minimum scores for the high and medium tiers; anything lower is low."""

    high: float = Field(default=0.75, ge=0.0, le=1.0)
    medium: float = Field(default=0.5, ge=0.0, le=1.0)


class SourceQualityConfig(BaseModel):
    """The parsed scoring rules."""

    default: DomainRule = DomainRule(score=0.5, label="unrated web")
    tiers: TierThresholds = Field(default_factory=TierThresholds)
    deny: list[str] = Field(default_factory=list)
    domains: dict[str, DomainRule] = Field(default_factory=dict)
    suffixes: dict[str, DomainRule] = Field(default_factory=dict)


class SourceQualityScorer:
    """Rates URLs (and whole evidence stores) with a `SourceQualityConfig`."""

    def __init__(self, config: SourceQualityConfig | None = None) -> None:
        self.config = config or SourceQualityConfig()

    @classmethod
    def from_path(cls, path: Path | None = None) -> SourceQualityScorer:
        """Load rules from YAML (the packaged defaults when `path` is None).

        Raises:
            ConfigurationError: If the file is missing or invalid.
        """
        path = path or DEFAULT_SOURCE_QUALITY_PATH
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return cls(SourceQualityConfig.model_validate(raw))
        except FileNotFoundError as exc:
            raise ConfigurationError(f"Source-quality config not found: {path}") from exc
        except (yaml.YAMLError, ValueError) as exc:
            raise ConfigurationError(f"Invalid source-quality config {path}: {exc}") from exc

    def rate(self, url: str) -> SourceRating:
        """Rate one URL by its host."""
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        cfg = self.config
        for domain in cfg.deny:
            if _matches(host, domain):
                return SourceRating(
                    score=0.0, tier="blocked", label="denied", rule=f"deny:{domain}"
                )
        matches = [d for d in cfg.domains if _matches(host, d)]
        if matches:
            domain = max(matches, key=len)
            return self._rating(cfg.domains[domain], f"domain:{domain}")
        for suffix, rule in cfg.suffixes.items():
            if host.endswith(suffix):
                return self._rating(rule, f"suffix:{suffix}")
        return SourceRating(
            score=cfg.default.score, tier="unrated", label=cfg.default.label, rule="default"
        )

    def _rating(self, rule: DomainRule, matched: str) -> SourceRating:
        return SourceRating(
            score=rule.score, tier=self._tier(rule.score), label=rule.label, rule=matched
        )

    def _tier(self, score: float) -> QualityTier:
        if score >= self.config.tiers.high:
            return "high"
        return "medium" if score >= self.config.tiers.medium else "low"


def _matches(host: str, domain: str) -> bool:
    domain = domain.lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)
