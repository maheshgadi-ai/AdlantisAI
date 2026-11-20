"""Builds the check-and-revise loop that every verified part of a kit passes through."""

from __future__ import annotations

from datetime import date

from adlantis.orchestrator.policy import AgentPolicy, GuardedChecker, GuardedReviser
from adlantis.orchestrator.review_loop import ReviewContext, ReviewLoop
from adlantis.orchestrator.team import AgentTeam
from adlantis.rules.context import RuleContext
from adlantis.rules.copy_assets import allowed_references
from adlantis.schemas.inputs import CampaignInputs
from adlantis.schemas.research import ResearchResult


def build_review_loop(
    inputs: CampaignInputs,
    team: AgentTeam,
    research: ResearchResult,
    *,
    today: date,
    policies: dict[str, AgentPolicy],
    concurrency: int,
    max_rounds: int,
) -> ReviewLoop:
    """The claim checker, code gate, rules engine, and targeted revision, wired for one run."""
    ctx = RuleContext(
        brand=inputs.brand,
        facts=inputs.facts,
        today=today,
        evidence_ids=research.evidence.usable_ids(),
        product_names=inputs.product.names,
    )
    return ReviewLoop(
        GuardedChecker(
            team.make_checker(ctx, research.evidence),
            policies.get("claim_checker", AgentPolicy()),
        ),
        GuardedReviser(team.copywriter, policies.get("copywriter", AgentPolicy())),
        ReviewContext(
            brand=inputs.brand,
            facts=inputs.facts,
            findings=research.findings,
            today=today,
            allowed_references=allowed_references(inputs.facts, research.findings, today),
            product_name=inputs.product.name,
        ),
        max_rounds=max_rounds,
        concurrency=concurrency,
    )
