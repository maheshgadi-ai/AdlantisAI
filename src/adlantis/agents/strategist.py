"""The strategist: turns inputs and research into a campaign strategy."""

from __future__ import annotations

import json
import secrets
from typing import ClassVar

from adlantis.agents.base import BaseAgent
from adlantis.llm.types import Message
from adlantis.schemas.strategy import CampaignStrategy, StrategyRequest, StrategyResult
from adlantis.tools.untrusted import render_findings


class StrategyError(ValueError):
    """Raised when no key message survives the reference checks."""


class Strategist(BaseAgent[StrategyRequest, StrategyResult]):
    """Writes the strategy, then keeps only messages backed by usable references."""

    name: ClassVar[str] = "strategist"
    role: ClassVar[str] = "strategist"
    prompt_file: ClassVar[str] = "strategist"
    input_schema: ClassVar[type[StrategyRequest]] = StrategyRequest
    output_schema: ClassVar[type[StrategyResult]] = StrategyResult

    def render_input(self, data: StrategyRequest) -> str:
        """Trusted inputs as JSON, with research kept inside the untrusted boundary."""
        trusted = {
            "brand": data.brand.model_dump(mode="json"),
            "product": data.product.model_dump(mode="json"),
            "approved_facts": [
                fact.model_dump(mode="json")
                for fact in data.facts.facts
                if not fact.is_expired(data.today)
            ],
        }
        research = render_findings(data.findings, secrets.token_hex(12))
        return f"{json.dumps(trusted, indent=2)}\n\nMarket research:\n{research}"

    def _run(self, data: StrategyRequest) -> StrategyResult:
        messages = [Message.system(self.system_prompt), Message.user(self.render_input(data))]
        llm = self.router.for_role(self.role)
        draft = llm.structured(messages, CampaignStrategy, trace_name="strategist.llm")
        return _checked(draft, data)


def _checked(draft: CampaignStrategy, data: StrategyRequest) -> StrategyResult:
    allowed = {f.id for f in data.facts.facts if not f.is_expired(data.today)}
    allowed |= {evidence_id for finding in data.findings for evidence_id in finding.evidence_ids}
    kept = [m for m in draft.key_messages if set(m.references) <= allowed]
    rejected = [m.message for m in draft.key_messages if not set(m.references) <= allowed]
    if not kept:
        raise StrategyError("No key message cites a usable fact or evidence record.")
    channels = [plan for plan in draft.channel_mix if plan.channel in data.product.channels]
    strategy = draft.model_copy(update={"key_messages": kept, "channel_mix": channels})
    return StrategyResult(strategy=strategy, rejected_messages=rejected)
