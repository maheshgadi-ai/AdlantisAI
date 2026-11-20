"""The single-prompt baseline: one model call writes a whole campaign, for evaluation."""

from __future__ import annotations

import json
from typing import ClassVar

from adlantis.agents.base import BaseAgent
from adlantis.llm.types import Message
from adlantis.rules.channels import load_channel_limits, required_mentions
from adlantis.rules.copy_assets import allowed_references, build_channel_copy, variant_gaps
from adlantis.schemas.baseline import BaselineDraft, BaselineRequest, BaselineResult
from adlantis.schemas.copy import ASSET_VARIANTS, ChannelDraft


class BaselineAgent(BaseAgent[BaselineRequest, BaselineResult]):
    """Runs on the copywriter's model, with no research, checker, or revision."""

    name: ClassVar[str] = "baseline"
    role: ClassVar[str] = "copywriter"
    prompt_file: ClassVar[str] = "baseline"
    input_schema: ClassVar[type[BaselineRequest]] = BaselineRequest
    output_schema: ClassVar[type[BaselineResult]] = BaselineResult

    def render_input(self, data: BaselineRequest) -> str:
        """The whole brief in one message."""
        limits = load_channel_limits()
        return json.dumps(
            {
                "brand": data.brand.model_dump(mode="json"),
                "product": data.product.model_dump(mode="json"),
                "approved_facts": [
                    fact.model_dump(mode="json")
                    for fact in data.facts.facts
                    if not fact.is_expired(data.today)
                ],
                "channels": {
                    channel: {
                        "variants": ASSET_VARIANTS[channel],
                        "writing_targets": limits.writing_targets(channel),
                    }
                    for channel in data.product.channels
                },
            },
            indent=2,
        )

    def _run(self, data: BaselineRequest) -> BaselineResult:
        messages = [Message.system(self.system_prompt), Message.user(self.render_input(data))]
        llm = self.router.for_role(self.role)
        draft = llm.structured(messages, BaselineDraft, trace_name="baseline.llm")
        return _assets(draft, data)


def _assets(draft: BaselineDraft, data: BaselineRequest) -> BaselineResult:
    allowed = allowed_references(data.facts, [], data.today)
    written = {item.channel: item.variants for item in reversed(draft.channels)}
    assets, rejected, gaps = [], [], []
    for channel in data.product.channels:
        variants = ChannelDraft(variants=written.get(channel, []))
        mentions = required_mentions(channel, data.product.name)
        built = build_channel_copy(variants, channel, allowed, mentions)
        assets += built.assets
        rejected += [f"{channel}: {reason}" for reason in built.rejected]
        gaps += variant_gaps(channel, built.rejected)
    return BaselineResult(
        positioning=draft.positioning,
        concept=draft.concept,
        assets=assets,
        rejected=rejected,
        gaps=gaps,
    )
