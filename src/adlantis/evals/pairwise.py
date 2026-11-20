"""Blind pairwise comparison, judged in both orders to cancel any position bias."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from adlantis.orchestrator.render_common import CHANNEL_TITLES
from adlantis.rules.text import REFERENCE_ID
from adlantis.schemas.inputs import CampaignInputs
from adlantis.schemas.judge import PairwiseRequest, PairwiseVerdict, SideScore
from adlantis.schemas.kit import CampaignKit

Outcome = Literal["team", "baseline", "split", "tie", "no_comparison"]
AskJudge = Callable[[PairwiseRequest], PairwiseVerdict]
CRITERIA = ("persuasiveness", "brand_fit", "clarity")


class JudgedOrder(BaseModel):
    """What the judge decided when the campaigns appeared in one order."""

    shown_first: Literal["team", "baseline"]
    winner: Literal["team", "baseline", "tie"]
    team_total: int
    baseline_total: int
    reason: str


class PairResult(BaseModel):
    """The combined result of judging one pair in both orders."""

    brief_id: str
    profile: str
    repeat: int
    outcome: Outcome
    team_scores: dict[str, float] = {}
    baseline_scores: dict[str, float] = {}
    position_bias: bool = False
    orders: list[JudgedOrder] = []
    error: str | None = None
    cost_usd: float = 0.0

    @property
    def team_total(self) -> float:
        """The agent team's mean rubric total."""
        return sum(self.team_scores.values())

    @property
    def baseline_total(self) -> float:
        """The baseline's mean rubric total."""
        return sum(self.baseline_scores.values())


def blind_copy(kit: CampaignKit) -> str:
    """Only the words a customer would read, with nothing that reveals how they were made."""
    blocks: list[str] = []
    ordered = sorted(kit.assets, key=lambda item: item.asset.channel)
    for item in ordered:
        asset = item.asset
        fields = [f"{name}: {text}" for name, text in asset.fields.items()]
        blocks.append("\n".join([CHANNEL_TITLES[asset.channel], *fields]))
    return REFERENCE_ID.sub("", "\n\n".join(blocks))


def judge_brief(inputs: CampaignInputs) -> str:
    """The neutral brief the judge sees, without the adversarial pressure."""
    product, brand = inputs.product, inputs.brand
    return (
        f"Brand: {brand.name}. Voice: {', '.join(brand.voice.tone)}. Audience: {brand.audience}\n"
        f"Product: {product.name}. {product.description}\nTarget market: {product.target_market}"
    )


def _mean(first: SideScore, second: SideScore) -> dict[str, float]:
    return {name: (getattr(first, name) + getattr(second, name)) / 2 for name in CRITERIA}


def _outcome(team_first: PairwiseVerdict, team_second: PairwiseVerdict) -> Outcome:
    votes = [
        {"A": "team", "B": "baseline", "tie": "tie"}[team_first.winner],
        {"A": "baseline", "B": "team", "tie": "tie"}[team_second.winner],
    ]
    return votes[0] if votes[0] == votes[1] else "split"


def _order(verdict: PairwiseVerdict, team_is_first: bool) -> JudgedOrder:
    team_side = verdict.campaign_a if team_is_first else verdict.campaign_b
    baseline_side = verdict.campaign_b if team_is_first else verdict.campaign_a
    first, second = ("team", "baseline") if team_is_first else ("baseline", "team")
    return JudgedOrder(
        shown_first=first,
        winner={"A": first, "B": second, "tie": "tie"}[verdict.winner],
        team_total=team_side.total,
        baseline_total=baseline_side.total,
        reason=verdict.reason,
    )


def compare(
    team: CampaignKit,
    baseline: CampaignKit,
    inputs: CampaignInputs,
    ask: AskJudge,
    **run: object,
) -> PairResult:
    """Judge a pair twice, swapping which campaign appears first."""
    if not team.assets or not baseline.assets:
        return PairResult(outcome="no_comparison", **run)
    brief = judge_brief(inputs)
    team_text, baseline_text = blind_copy(team), blind_copy(baseline)
    team_first = ask(PairwiseRequest(brief=brief, campaign_a=team_text, campaign_b=baseline_text))
    team_second = ask(PairwiseRequest(brief=brief, campaign_a=baseline_text, campaign_b=team_text))
    return PairResult(
        outcome=_outcome(team_first, team_second),
        team_scores=_mean(team_first.campaign_a, team_second.campaign_b),
        baseline_scores=_mean(team_first.campaign_b, team_second.campaign_a),
        position_bias=team_first.winner == team_second.winner != "tie",
        orders=[_order(team_first, True), _order(team_second, False)],
        **run,
    )
