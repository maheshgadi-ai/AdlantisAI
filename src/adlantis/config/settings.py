"""Application settings loaded from environment variables and `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["openai", "anthropic"]


class Settings(BaseSettings):
    """Runtime configuration: credentials, transport behavior, and overrides.

    Which model each role uses lives in the routing profiles (`config/models*.yaml`). The
    fields here only override them:

    - `MODEL__<ROLE>=provider:model-id` overrides one role (e.g. `MODEL__COPYWRITER`).
    - `LLM_PROVIDER` plus `OPENAI_MODEL` / `ANTHROPIC_MODEL` override the `default` entry.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        env_ignore_empty=True,  # a blank line in .env (as in .env.example) means "use the default"
        extra="ignore",
    )

    # Credentials
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    # Model routing overrides (all optional)
    models_config_path: Path | None = None
    llm_provider: ProviderName | None = None
    openai_model: str | None = None
    anthropic_model: str | None = None
    model: dict[str, str] = Field(default_factory=dict)

    # Transport behavior shared by all providers. Long structured calls at high reasoning
    # effort can take minutes, and a timeout that is too short retries (and bills) them.
    llm_timeout_seconds: float = Field(default=300.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)

    # Research tools
    tavily_api_key: SecretStr | None = None
    tool_cache_dir: Path | None = None  # set to enable the on-disk tool-result cache
    tool_cache_ttl_hours: float = Field(default=24.0, gt=0)
    source_quality_path: Path | None = None  # override config/source_quality.yaml

    # Feature flags
    enable_images: bool = False

    # Observability
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"

    # Logging
    log_level: str = "INFO"

    @property
    def tracing_enabled(self) -> bool:
        """Tracing is on only when both Langfuse keys are present and non-empty."""
        return bool(
            self.langfuse_public_key
            and self.langfuse_public_key.get_secret_value()
            and self.langfuse_secret_key
            and self.langfuse_secret_key.get_secret_value()
        )

    def api_key(self, provider: ProviderName) -> str | None:
        """Return the API key for `provider`, or None if it isn't set."""
        secret = self.openai_api_key if provider == "openai" else self.anthropic_api_key
        return (secret.get_secret_value() or None) if secret else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached `Settings` instance."""
    return Settings()
