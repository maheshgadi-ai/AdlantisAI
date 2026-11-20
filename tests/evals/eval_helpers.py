"""Shared fixtures for evaluation tests. Nothing here calls a model."""

from __future__ import annotations

from pathlib import Path

from adlantis.evals.briefs import load_briefs
from adlantis.evals.pairwise import PairResult
from adlantis.schemas.judge import PairwiseVerdict
from tests.orchestrator.kit_helpers import make_kit, reviewed

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
BRIEFS = load_briefs()
BY_ID = {brief.id: brief for brief in BRIEFS}


def kit_with(text: str, asset_id: str = "email-1"):
    item = reviewed(asset_id)
    item.asset.fields["body"] = text
    return make_kit(item)


def verdict(a: int, b: int, winner: str) -> PairwiseVerdict:
    scores = {"persuasiveness": a, "brand_fit": a, "clarity": a}
    other = {"persuasiveness": b, "brand_fit": b, "clarity": b}
    return PairwiseVerdict(campaign_a=scores, campaign_b=other, winner=winner, reason="Clearer.")


def pair(outcome: str = "team", brief_id: str = "AB-02", **changes: object) -> PairResult:
    values = {
        "brief_id": brief_id,
        "profile": "budget",
        "repeat": 1,
        "outcome": outcome,
        "team_scores": {"persuasiveness": 4.0, "brand_fit": 4.0, "clarity": 4.0},
        "baseline_scores": {"persuasiveness": 3.0, "brand_fit": 3.0, "clarity": 3.0},
    }
    return PairResult(**{**values, **changes})
