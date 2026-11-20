"""Route each role to its configured provider and model.

Agents call `router.for_role("copywriter")` and never choose a model themselves. One
router serves a whole run, so providers can be mixed and usage is shared.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from adlantis.config.images import load_image_config
from adlantis.config.models import (
    DEFAULT_ROLE,
    ConfigurationError,
    ModelsConfig,
    ModelSpec,
    load_models_config,
    profile_path,
)
from adlantis.config.role_rules import enforce_role_rules
from adlantis.config.settings import ProviderName, Settings
from adlantis.llm.anthropic_provider import AnthropicProvider
from adlantis.llm.base import LLMProvider
from adlantis.llm.budget import BudgetCap
from adlantis.llm.images import ImageGenerator
from adlantis.llm.openai_provider import OpenAIProvider
from adlantis.llm.pricing import RunUsage
from adlantis.observability.tracing import Tracer

logger = logging.getLogger(__name__)

ClientFactory = Callable[[ProviderName], Any]

_PROVIDER_CLASSES: dict[ProviderName, type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


class ModelRouter:
    """Hand out role-bound `LLMProvider` instances that share tracing and usage."""

    def __init__(
        self,
        settings: Settings,
        models: ModelsConfig,
        *,
        tracer: Tracer | None = None,
        usage: RunUsage | None = None,
        client_factory: ClientFactory | None = None,
        max_cost_usd: float | None = None,
    ) -> None:
        self.settings = settings
        self.models = models
        self.tracer = tracer or Tracer()
        self.usage = usage or RunUsage()
        self.budget = None if max_cost_usd is None else BudgetCap(max_cost_usd, self.usage)
        self._client_factory = client_factory or self._sdk_client
        self._clients: dict[ProviderName, Any] = {}
        self._providers: dict[str, LLMProvider] = {}
        self._lock = threading.Lock()  # agents may run concurrently in worker threads

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        profile: str | None = None,
        tracer: Tracer | None = None,
        max_cost_usd: float | None = None,
    ) -> ModelRouter:
        """Build a router for a named profile, else `MODELS_CONFIG_PATH`, else the budget profile.

        Raises:
            ConfigurationError: If the resolved routing breaks a role rule.
        """
        path = profile_path(profile) if profile else settings.models_config_path
        models = load_models_config(path)
        enforce_role_rules(models, settings)
        return cls(settings, models, tracer=tracer, max_cost_usd=max_cost_usd)

    def resolve(self, role: str) -> ModelSpec:
        """Return the model spec a role will use, after overrides.

        Raises:
            ConfigurationError: If the role is not configured, so a misspelled role can never
                fall back to the default model and bypass the routing rules.
        """
        if role.lower() != DEFAULT_ROLE and role.lower() not in self.models.roles:
            raise ConfigurationError(f"Unknown role {role!r}")
        return self.models.resolve(role, self.settings)

    def for_role(self, role: str) -> LLMProvider:
        """Return the provider for `role`, creating it on first use.

        Raises:
            ConfigurationError: If the role's provider has no API key configured.
        """
        role = role.lower()
        with self._lock:
            if role not in self._providers:
                spec = self.resolve(role)
                self._providers[role] = _PROVIDER_CLASSES[spec.provider](
                    spec,
                    client=self._client(spec.provider),
                    role=role,
                    tracer=self.tracer,
                    usage=self.usage,
                    pricing=self.models.price_for(spec.model),
                    budget=self.budget,
                )
                logger.info(
                    "model routed",
                    extra={
                        "role": role,
                        "model": spec.label,
                        "validated": self.models.capabilities_for(spec.model) is not None,
                    },
                )
            return self._providers[role]

    def image_generator(self) -> ImageGenerator:
        """The image generator for this run, sharing its budget and tracing."""
        with self._lock:
            client = self._client("openai")
        config = load_image_config()
        return ImageGenerator(config, client, budget=self.budget, tracer=self.tracer)

    def _client(self, provider: ProviderName) -> Any:
        if provider not in self._clients:
            self._clients[provider] = self._client_factory(provider)
        return self._clients[provider]

    def _sdk_client(self, provider: ProviderName) -> Any:
        key = self.settings.api_key(provider)
        if not key:
            env_name = f"{provider.upper()}_API_KEY"
            raise ConfigurationError(f"{env_name} is not set; add it to your environment or .env")
        timeout, retries = self.settings.llm_timeout_seconds, self.settings.llm_max_retries
        if provider == "openai":
            import openai

            return openai.OpenAI(api_key=key, timeout=timeout, max_retries=retries)
        import anthropic

        return anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=retries)
