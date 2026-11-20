from pathlib import Path

import pytest

from adlantis.config import ConfigurationError
from adlantis.tools.source_quality import (
    DomainRule,
    SourceQualityConfig,
    SourceQualityScorer,
)

CONFIG = SourceQualityConfig(
    default=DomainRule(score=0.5, label="web"),
    deny=["spam.example"],
    domains={
        "nih.gov": DomainRule(score=0.85, label="government"),
        "pmc.ncbi.nlm.nih.gov": DomainRule(score=0.95, label="peer-reviewed"),
        "youtube.com": DomainRule(score=0.2, label="video"),
    },
    suffixes={".edu": DomainRule(score=0.85, label="university")},
)


@pytest.mark.parametrize(
    ("url", "tier", "rule"),
    [
        ("https://pmc.ncbi.nlm.nih.gov/articles/1", "high", "domain:pmc.ncbi.nlm.nih.gov"),
        ("https://www.nih.gov/news", "high", "domain:nih.gov"),  # www ignored
        ("https://sub.nih.gov/x", "high", "domain:nih.gov"),  # subdomains match
        ("https://notnih.gov/x", "unrated", "default"),  # look-alikes don't match
        ("https://m.youtube.com/watch", "low", "domain:youtube.com"),
        ("https://cs.stanford.edu/paper.pdf", "high", "suffix:.edu"),
        ("https://a.spam.example/page", "blocked", "deny:spam.example"),
        ("https://unknown.example/page", "unrated", "default"),  # unknown is not weak
    ],
)
def test_matching_order_and_tiers(url: str, tier: str, rule: str) -> None:
    rating = SourceQualityScorer(CONFIG).rate(url)
    assert (rating.tier, rating.rule) == (tier, rule)


def test_deny_beats_domain_rules() -> None:
    config = CONFIG.model_copy(update={"deny": ["youtube.com"]})
    assert SourceQualityScorer(config).rate("https://youtube.com/x").score == 0.0


def test_packaged_rules_rate_known_sources_sensibly() -> None:
    scorer = SourceQualityScorer.from_path()
    tiers = {u: scorer.rate(u).tier for u in [
        "https://arxiv.org/abs/2601.00001", "https://www.iea.org/reports/x",
        "https://en.wikipedia.org/wiki/X", "https://www.youtube.com/watch?v=1",
        "https://url.htx.mybluehost.me/page", "https://eureka.patsnap.com/report",
    ]}  # fmt: skip
    assert list(tiers.values()) == ["high", "high", "medium", "low", "blocked", "low"]


def test_invalid_or_missing_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        SourceQualityScorer.from_path(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("domains: {x.org: {score: 3, label: too high}}\n")
    with pytest.raises(ConfigurationError, match="Invalid source-quality config"):
        SourceQualityScorer.from_path(bad)


def test_unrated_keeps_neutral_default_score() -> None:
    rating = SourceQualityScorer.from_path().rate("https://some-unknown-site.example/page")
    assert (rating.tier, rating.score, rating.rule) == ("unrated", 0.5, "default")
