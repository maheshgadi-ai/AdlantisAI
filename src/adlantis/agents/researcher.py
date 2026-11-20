"""The researcher: gathers cited market context from the web."""

from __future__ import annotations

import logging
from typing import ClassVar

from adlantis.agents.base import BaseAgent
from adlantis.llm.base import LLMProvider
from adlantis.llm.router import ModelRouter
from adlantis.llm.types import Message, ToolSpec
from adlantis.prompts import load_prompt
from adlantis.schemas.research import (
    ResearchBrief,
    ResearchDraft,
    ResearchLimits,
    ResearchResult,
)
from adlantis.tools.grounding import accept_findings
from adlantis.tools.registry import ToolRegistry
from adlantis.tools.research_session import SESSION_TOOLS, ResearchSession
from adlantis.tools.source_quality import SourceQualityScorer

logger = logging.getLogger(__name__)

_FINALIZE_MARKER = "<!-- section: finalize -->"
NO_SEARCH_GAP = "Web search is not configured, so no market research was gathered."
BUDGET_GAP = "The research budget was reached before findings could be written."


class Researcher(BaseAgent[ResearchBrief, ResearchResult]):
    """Searches, reads, and reports findings that code has checked against their sources."""

    name: ClassVar[str] = "researcher"
    role: ClassVar[str] = "researcher"
    prompt_file: ClassVar[str] = "researcher"
    input_schema: ClassVar[type[ResearchBrief]] = ResearchBrief
    output_schema: ClassVar[type[ResearchResult]] = ResearchResult

    def __init__(
        self,
        router: ModelRouter,
        tools: ToolRegistry,
        scorer: SourceQualityScorer,
        limits: ResearchLimits | None = None,
    ) -> None:
        super().__init__(router)
        self.tools = tools
        self.scorer = scorer
        self.limits = limits or ResearchLimits()

    @property
    def system_prompt(self) -> str:
        """The instructions for the research phase."""
        return load_prompt(self.prompt_file).split(_FINALIZE_MARKER)[0].strip()

    @property
    def finalize_prompt(self) -> str:
        """The instructions for reporting findings."""
        return load_prompt(self.prompt_file).split(_FINALIZE_MARKER)[1].strip()

    def render_input(self, data: ResearchBrief) -> str:
        """The brief, plus the budget the model has to plan within."""
        budget = (
            f"Research budget: {self.limits.max_searches} searches and "
            f"{self.limits.max_fetches} page reads. Calls beyond this are refused."
        )
        return f"{data.model_dump_json(indent=2)}\n\n{budget}"

    def _run(self, data: ResearchBrief) -> ResearchResult:
        if "web_search" not in self.tools:
            return ResearchResult(gaps=[NO_SEARCH_GAP])
        session = ResearchSession(self.tools, self.scorer, self.limits)
        llm = self.router.for_role(self.role)
        messages = [Message.system(self.system_prompt), Message.user(self.render_input(data))]
        self._gather(llm, session, messages)
        if self._over_budget():
            return ResearchResult(evidence=session.store, gaps=[BUDGET_GAP], stats=session.stats)
        messages.append(Message.user(self.finalize_prompt))
        draft = llm.structured(
            messages,
            ResearchDraft,
            max_tokens=self.limits.final_output_tokens,
            trace_name="researcher.findings",
        )
        findings, rejected = accept_findings(draft, session.store)
        logger.info(
            "research finished",
            extra={"findings": len(findings), "rejected": len(rejected)},
        )
        return ResearchResult(
            findings=findings,
            rejected=rejected,
            evidence=session.store,
            gaps=draft.gaps,
            stats=session.stats,
        )

    def _gather(self, llm: LLMProvider, session: ResearchSession, messages: list[Message]) -> None:
        specs = [
            ToolSpec(
                name=t.name, description=t.description, parameters=t.schema.model_json_schema()
            )
            for t in SESSION_TOOLS
        ]
        for _ in range(self.limits.max_turns):
            if self._over_budget():
                return
            response = llm.complete(
                messages,
                tools=specs,
                tool_choice="auto",
                max_tokens=self.limits.turn_output_tokens,
                trace_name="researcher.turn",
            )
            messages.append(response.to_message())
            if not response.tool_calls:
                return
            for call in response.tool_calls:
                messages.append(Message.tool(call.id, session.execute(call.name, call.arguments)))

    def _over_budget(self) -> bool:
        limit = self.limits.max_cost_usd
        return limit is not None and self.router.usage.cost_usd >= limit
