"""The agents a campaign run uses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from adlantis.agents import ClaimChecker, Copywriter, Designer, Researcher, Strategist
from adlantis.llm.router import ModelRouter
from adlantis.rules.context import RuleContext
from adlantis.schemas.evidence_store import EvidenceStore
from adlantis.schemas.research import ResearchLimits
from adlantis.tools.registry import ToolRegistry
from adlantis.tools.source_quality import SourceQualityScorer


@dataclass(frozen=True)
class AgentTeam:
    """One agent per step. The claim checker is built once the evidence is known."""

    researcher: Any
    strategist: Any
    copywriter: Any
    designer: Any
    make_checker: Callable[[RuleContext, EvidenceStore], Any]


def build_team(router: ModelRouter, tools: ToolRegistry, limits: ResearchLimits) -> AgentTeam:
    """The production team, with every agent routed through `router`."""
    return AgentTeam(
        researcher=Researcher(router, tools, SourceQualityScorer.from_path(), limits),
        strategist=Strategist(router),
        copywriter=Copywriter(router),
        designer=Designer(router),
        make_checker=lambda ctx, evidence: ClaimChecker(router, ctx, evidence),
    )
