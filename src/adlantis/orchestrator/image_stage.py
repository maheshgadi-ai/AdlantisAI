"""Generates images from verified prompts, when image generation is switched on."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from adlantis.llm.images import ImageGenerator
from adlantis.llm.types import LLMError
from adlantis.orchestrator.run_log import RunLog
from adlantis.rules.image_prompts import sendable_problems
from adlantis.schemas.design import GeneratedImage, ImagePrompt
from adlantis.schemas.inputs import CampaignInputs


async def generate_images(
    prompts: list[ImagePrompt],
    inputs: CampaignInputs,
    images: ImageGenerator | None,
    run_dir: Path | None,
    log: RunLog,
    slots: asyncio.Semaphore,
) -> list[GeneratedImage]:
    """Generate one image per prompt. Passing no generator means image generation is off."""
    if images is None or run_dir is None:
        log.record("images", "skipped", "Image generation is off.")
        return []
    made = await asyncio.gather(
        *(_generate(prompt, inputs, images, run_dir, log, slots) for prompt in prompts)
    )
    return [image for image in made if image is not None]


async def _generate(
    prompt: ImagePrompt,
    inputs: CampaignInputs,
    images: ImageGenerator,
    run_dir: Path,
    log: RunLog,
    slots: asyncio.Semaphore,
) -> GeneratedImage | None:
    stage = f"image:{prompt.asset_id}"
    problems = sendable_problems(prompt.prompt, inputs.brand, inputs.product.names)
    if problems:
        log.record(stage, "skipped", "; ".join(problems))
        return None
    try:
        async with slots:
            result = await asyncio.to_thread(images.generate, prompt.prompt, prompt.size)
    except LLMError as exc:
        log.record(stage, "failed", str(exc))
        return None
    file = f"images/{prompt.asset_id}.png"
    path = run_dir / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(result.data)
    log.record(stage, "finished", file)
    return GeneratedImage(
        asset_id=prompt.asset_id,
        file=file,
        model=result.model,
        alt_text=prompt.alt_text,
        sha256=hashlib.sha256(result.data).hexdigest(),
        cost_usd=result.cost_usd,
    )
