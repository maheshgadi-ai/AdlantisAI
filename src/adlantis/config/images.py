"""Settings for optional image generation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from adlantis.config.models import CONFIG_DIR, DEPRECATIONS_PATH, ConfigurationError

IMAGE_CONFIG_PATH = CONFIG_DIR / "image_models.yaml"


class ImagePricing(BaseModel):
    """Prices in USD per one million tokens."""

    model_config = ConfigDict(extra="forbid")

    text_input_per_mtok: float = Field(gt=0)
    image_input_per_mtok: float = Field(gt=0)
    image_output_per_mtok: float = Field(gt=0)


class ImageModelConfig(BaseModel):
    """Which image model to call, and what one image may cost."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    quality: str = Field(min_length=1)
    default_size: str = Field(pattern=r"^\d+x\d+$")
    channel_sizes: dict[str, str] = Field(default_factory=dict)
    reserve_usd_per_image: float = Field(gt=0)
    pricing: ImagePricing

    def size_for(self, channel: str) -> str:
        """The image size for a channel."""
        return self.channel_sizes.get(channel, self.default_size)


@lru_cache(maxsize=2)
def load_image_config(path: Path = IMAGE_CONFIG_PATH) -> ImageModelConfig:
    """Read the image settings and refuse a model the provider has retired.

    Raises:
        ConfigurationError: If the file is invalid or names a deprecated model.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        settings = data["image"]
        config = ImageModelConfig(**settings, pricing=data["pricing"][settings["model"]])
    except (OSError, KeyError, TypeError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"Invalid image config {path}: {exc}") from exc
    deprecated = yaml.safe_load(DEPRECATIONS_PATH.read_text(encoding="utf-8"))["deprecated"]
    gone = deprecated.get(config.model)
    if gone:
        raise ConfigurationError(
            f"{config.model} is deprecated (shutdown {gone['shutdown']}); use {gone['replacement']}"
        )
    return config
