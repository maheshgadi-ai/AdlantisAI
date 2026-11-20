"""Optional image generation through the OpenAI Images API."""

from __future__ import annotations

import base64
import binascii
from typing import Any, NamedTuple

from adlantis.config.images import ImageModelConfig
from adlantis.llm.budget import BudgetCap, BudgetExceeded
from adlantis.llm.types import LLMError
from adlantis.observability.tracing import Tracer


class ImageResult(NamedTuple):
    """One generated image and what it cost."""

    data: bytes
    model: str
    cost_usd: float


class ImageGenerator:
    """Generates one image at a time, inside the run's budget."""

    def __init__(
        self,
        config: ImageModelConfig,
        client: Any,
        *,
        budget: BudgetCap | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self._budget = budget
        self._tracer = tracer or Tracer()

    def generate(self, prompt: str, size: str) -> ImageResult:
        """Generate an image.

        Raises:
            BudgetExceeded: If the image could pass the budget cap.
            LLMError: If the provider fails or returns no usable image.
        """
        reserve = self.config.reserve_usd_per_image
        if self._budget is not None:
            self._budget.reserve(reserve)
        try:
            with self._tracer.observe(
                "image.generate", as_type="generation", model=self.config.model, input=prompt
            ) as obs:
                response = self._call(prompt, size)
                cost = self._cost(getattr(response, "usage", None))
                if self._budget is not None:
                    self._budget.charge(cost)
                obs.update(cost_details={"total": cost})
            return ImageResult(_decode(response), self.config.model, cost)
        finally:
            if self._budget is not None:
                self._budget.release(reserve)

    def _call(self, prompt: str, size: str) -> Any:
        try:
            return self._client.images.generate(
                model=self.config.model,
                prompt=prompt,
                size=size,
                quality=self.config.quality,
                n=1,
                output_format="png",
            )
        except (BudgetExceeded, LLMError):
            raise
        except Exception as exc:  # the SDK raises many types; none may stop the campaign
            raise LLMError(f"Image generation failed: {type(exc).__name__}") from exc

    def _cost(self, usage: Any) -> float:
        """The billed cost. With no usage reported, the full reserve is charged."""
        if usage is None:
            return self.config.reserve_usd_per_image
        prices = self.config.pricing
        details = getattr(usage, "input_tokens_details", None)
        text = getattr(details, "text_tokens", None)
        image = getattr(details, "image_tokens", 0) or 0
        text = usage.input_tokens - image if text is None else text
        total = (
            text * prices.text_input_per_mtok
            + image * prices.image_input_per_mtok
            + usage.output_tokens * prices.image_output_per_mtok
        )
        return total / 1_000_000


def _decode(response: Any) -> bytes:
    images = getattr(response, "data", None) or []
    encoded = getattr(images[0], "b64_json", None) if images else None
    if not encoded:
        raise LLMError("Image generation returned no image data.")
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise LLMError("Image generation returned unreadable image data.") from exc
