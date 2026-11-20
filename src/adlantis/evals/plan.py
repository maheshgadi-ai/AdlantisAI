"""What an evaluation will run, and what it is expected to cost before anything is billed."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from adlantis.config import ModelsConfig, Pricing, Settings, load_profile
from adlantis.evals.briefs import AdversarialBrief
from adlantis.evals.claim_labels import load_claim_labels
from adlantis.orchestrator.cost_estimate import (
    estimate_baseline_cost,
    estimate_campaign_cost,
    estimate_research_cost,
    token_cost,
)
from adlantis.schemas.copy import ASSET_VARIANTS

RUN_CAPS_USD = {"budget": 1.00, "default": 2.50}
BASELINE_CAP_USD = 0.50
AUDIT_CAP_USD = 0.50
JUDGE_CAP_USD = 0.80
TRIAGE_CAP_USD = 0.50
RERUN_TEAM_CAP_USD = 0.60
RERUN_JUDGE_CAP_USD = 0.80
JUDGE_FLOOR_USD = 0.20  # one budget-profile judge call, with room for its input
CHECKER_FLOOR_USD = 0.20  # one budget-profile claim-checker call, with room for its input
RECALL_CAP_USD = {"budget": 0.75, "default": 1.50}
_AUDIT_CALL = (3000, 1200)
_JUDGE_CALL = (6000, 500)
_RECALL_CALL = (2000, 500)
_JUDGE_ORDERS = 2
_SAFETY_MARGIN = 1.5


@dataclass(frozen=True)
class EvalPlan:
    """Which briefs to run, on which profiles, and how many times."""

    name: str
    brief_ids: tuple[str, ...] | None
    repeats: dict[str, int]


TIERS: dict[str, EvalPlan] = {
    "smoke": EvalPlan("smoke", ("AB-02", "AB-08", "AB-09"), {"budget": 1}),
    "standard": EvalPlan("standard", None, {"budget": 2, "default": 1}),
    "full": EvalPlan("full", None, {"budget": 2, "default": 2}),
    "budget": EvalPlan("budget", None, {"budget": 2}),
}


class CostLine(BaseModel):
    """The expected cost of one kind of work on one profile, in USD."""

    profile: str
    work: str
    calls: int
    usd: float


class PlanEstimate(BaseModel):
    """The expected cost of a whole evaluation, in USD."""

    tier: str
    briefs: int
    lines: list[CostLine]

    @property
    def typical_usd(self) -> float:
        """The expected total."""
        return sum(line.usd for line in self.lines)

    @property
    def suggested_cap_usd(self) -> float:
        """A hard cap with room for variance, rounded up to a whole dollar."""
        return float(math.ceil(self.typical_usd * _SAFETY_MARGIN))


def _price(models: ModelsConfig, role: str, settings: Settings) -> Pricing:
    return models.price_for(models.resolve(role, settings).model)


def selected_briefs(plan: EvalPlan, briefs: Sequence[AdversarialBrief]) -> list[AdversarialBrief]:
    """The briefs a plan covers, in their listed order."""
    return [b for b in briefs if plan.brief_ids is None or b.id in plan.brief_ids]


def estimate_plan(
    plan: EvalPlan, briefs: Sequence[AdversarialBrief], settings: Settings
) -> PlanEstimate:
    """Estimate every billed call. Searches are free here because the web is a fixture."""
    chosen = selected_briefs(plan, briefs)
    snippets = len(load_claim_labels().snippets)
    lines: list[CostLine] = []
    for profile, repeats in plan.repeats.items():
        models = load_profile(profile)
        research = estimate_research_cost(models, settings).typical_model_usd
        team = sum(
            research + estimate_campaign_cost(models, settings, b.channels).typical_usd
            for b in chosen
        )
        audits = sum(ASSET_VARIANTS[c] for b in chosen for c in b.channels)
        runs = len(chosen) * repeats
        audit_each = token_cost(*_AUDIT_CALL, _price(models, "claim_checker", settings))
        judge_each = token_cost(*_JUDGE_CALL, _price(models, "judge", settings))
        baseline_each = estimate_baseline_cost(models, settings).typical_usd
        lines += [
            CostLine(profile=profile, work="Agent team runs", calls=runs, usd=team * repeats),
            CostLine(profile=profile, work="Baseline runs", calls=runs, usd=runs * baseline_each),
            CostLine(
                profile=profile,
                work="Baseline claim audits",
                calls=audits * repeats,
                usd=audits * repeats * audit_each,
            ),
            CostLine(
                profile=profile,
                work="Blind judging, both orders",
                calls=runs * _JUDGE_ORDERS,
                usd=runs * _JUDGE_ORDERS * judge_each,
            ),
            CostLine(
                profile=profile,
                work="Claim-extraction recall",
                calls=snippets,
                usd=snippets * token_cost(*_RECALL_CALL, _price(models, "claim_checker", settings)),
            ),
        ]
    return PlanEstimate(tier=plan.name, briefs=len(chosen), lines=lines)
