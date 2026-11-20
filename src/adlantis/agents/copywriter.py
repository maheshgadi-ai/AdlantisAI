"""The copywriter: writes cited copy for one channel and proposes targeted revisions."""

from __future__ import annotations

import json
import secrets
from datetime import date
from typing import ClassVar

from adlantis.agents.base import BaseAgent
from adlantis.llm.types import Message
from adlantis.prompts import load_prompt
from adlantis.rules.channels import key_message_limit, load_channel_limits, required_mentions
from adlantis.rules.copy_assets import allowed_references, build_channel_copy
from adlantis.schemas.copy import (
    ASSET_VARIANTS,
    ChannelCopy,
    ChannelDraft,
    CopyRequest,
    RevisionPlan,
    RevisionRequest,
)
from adlantis.schemas.facts import FactSheet
from adlantis.tools.untrusted import render_findings

_REVISE_MARKER = "<!-- section: revise -->"
__all__ = ["Copywriter", "allowed_references"]


class Copywriter(BaseAgent[CopyRequest, ChannelCopy]):
    """Writes copy whose factual statements cite approved facts or evidence."""

    name: ClassVar[str] = "copywriter"
    role: ClassVar[str] = "copywriter"
    prompt_file: ClassVar[str] = "copywriter"
    input_schema: ClassVar[type[CopyRequest]] = CopyRequest
    output_schema: ClassVar[type[ChannelCopy]] = ChannelCopy

    @property
    def system_prompt(self) -> str:
        """The instructions for writing new copy."""
        return load_prompt(self.prompt_file).split(_REVISE_MARKER)[0].strip()

    @property
    def revise_prompt(self) -> str:
        """The instructions for targeted revisions."""
        return load_prompt(self.prompt_file).split(_REVISE_MARKER)[1].strip()

    def render_input(self, data: CopyRequest) -> str:
        """The brief as JSON, with research kept inside the untrusted boundary."""
        trusted = {
            "channel": data.channel,
            "variants": ASSET_VARIANTS[data.channel],
            "writing_targets": load_channel_limits().writing_targets(data.channel),
            "required_mentions": required_mentions(data.channel, data.product.name),
            "key_message_within_chars": key_message_limit(data.channel),
            "brand": data.brand.model_dump(mode="json"),
            "product": data.product.model_dump(mode="json"),
            "strategy": data.strategy.model_dump(mode="json"),
            "approved_facts": _active_facts(data.facts, data.today),
        }
        research = render_findings(data.findings, secrets.token_hex(12))
        return f"{json.dumps(trusted, indent=2)}\n\nMarket research:\n{research}"

    def _run(self, data: CopyRequest) -> ChannelCopy:
        messages = [Message.system(self.system_prompt), Message.user(self.render_input(data))]
        llm = self.router.for_role(self.role)
        draft = llm.structured(messages, ChannelDraft, trace_name="copywriter.llm")
        allowed = allowed_references(data.facts, data.findings, data.today)
        mentions = required_mentions(data.channel, data.product.name)
        return build_channel_copy(draft, data.channel, allowed, mentions)

    def revise(self, data: RevisionRequest) -> RevisionPlan:
        """Propose targeted edits for the open issues on one asset."""
        trusted = {
            "asset": data.asset.model_dump(mode="json"),
            "issues": [issue.model_dump(mode="json") for issue in data.issues],
            "writing_targets": load_channel_limits().writing_targets(data.asset.channel),
            "banned_words": data.brand.banned_words,
            "banned_claim_types": data.brand.banned_claim_types,
            "required_mentions": data.required_mentions,
            "key_message_within_chars": key_message_limit(data.asset.channel),
            "approved_glossary": [entry.wording for entry in data.brand.glossary],
            "approved_facts": _active_facts(data.facts, data.today),
        }
        research = render_findings(data.findings, secrets.token_hex(12))
        content = f"{json.dumps(trusted, indent=2)}\n\nMarket research:\n{research}"
        messages = [Message.system(self.revise_prompt), Message.user(content)]
        llm = self.router.for_role(self.role)
        return llm.structured(messages, RevisionPlan, trace_name="copywriter.revise")


def _active_facts(facts: FactSheet, today: date) -> list[dict]:
    return [fact.model_dump(mode="json") for fact in facts.facts if not fact.is_expired(today)]
