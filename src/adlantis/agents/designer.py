"""The visual designer: proposes one image prompt per shipped asset."""

from __future__ import annotations

import json
from typing import ClassVar

from adlantis.agents.base import BaseAgent
from adlantis.config.images import load_image_config
from adlantis.llm.types import Message
from adlantis.rules.image_prompts import image_prompt_problems, with_safety_suffix
from adlantis.schemas.design import (
    TEXT_ONLY_CHANNELS,
    DesignDraft,
    DesignRequest,
    DesignResult,
    DraftImagePrompt,
    ImagePrompt,
    RejectedImagePrompt,
)


class Designer(BaseAgent[DesignRequest, DesignResult]):
    """Writes image prompts. Code refuses any that request real people, brands, or logos."""

    name: ClassVar[str] = "designer"
    role: ClassVar[str] = "designer"
    prompt_file: ClassVar[str] = "designer"
    input_schema: ClassVar[type[DesignRequest]] = DesignRequest
    output_schema: ClassVar[type[DesignResult]] = DesignResult

    def render_input(self, data: DesignRequest) -> str:
        """The look of the campaign and the assets to illustrate."""
        return json.dumps(
            {
                "tone": data.brand.voice.tone,
                "colors": [color.model_dump() for color in data.brand.colors],
                "concept": data.strategy.concept,
                "assets": [
                    {"asset_id": a.asset_id, "channel": a.channel, "fields": a.fields}
                    for a in _visual_assets(data)
                ],
            },
            indent=2,
        )

    def _run(self, data: DesignRequest) -> DesignResult:
        if not _visual_assets(data):
            return DesignResult()
        messages = [Message.system(self.system_prompt), Message.user(self.render_input(data))]
        llm = self.router.for_role(self.role)
        draft = llm.structured(messages, DesignDraft, trace_name="designer.llm")
        return _checked(draft, data)


def _visual_assets(data: DesignRequest) -> list:
    return [asset for asset in data.assets if asset.channel not in TEXT_ONLY_CHANNELS]


def _checked(draft: DesignDraft, data: DesignRequest) -> DesignResult:
    config = load_image_config()
    proposals: dict[str, DraftImagePrompt] = {}
    for item in draft.prompts:
        proposals.setdefault(item.asset_id, item)
    prompts: list[ImagePrompt] = []
    rejected: list[RejectedImagePrompt] = []
    for asset in _visual_assets(data):
        item = proposals.get(asset.asset_id)
        problems = ["no prompt was returned"] if item is None else _problems(item, data)
        if problems:
            rejected.append(
                RejectedImagePrompt(asset_id=asset.asset_id, reason="; ".join(problems))
            )
            continue
        prompts.append(
            ImagePrompt(
                asset_id=asset.asset_id,
                channel=asset.channel,
                prompt=with_safety_suffix(item.prompt),
                alt_text=item.alt_text.strip(),
                size=config.size_for(asset.channel),
            )
        )
    return DesignResult(prompts=prompts, rejected=rejected)


def _problems(item: DraftImagePrompt, data: DesignRequest) -> list[str]:
    if not item.prompt.strip() or not item.alt_text.strip():
        return ["the prompt or its description is empty"]
    text = f"{item.prompt}\n{item.alt_text}"
    return image_prompt_problems(text, data.brand, data.product.names)
