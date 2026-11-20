from concurrent.futures import ThreadPoolExecutor

import pytest

from adlantis.config import ConfigurationError, ModelsConfig, Settings
from adlantis.llm import Message, ModelRouter
from adlantis.llm.anthropic_provider import AnthropicProvider
from adlantis.llm.openai_provider import OpenAIProvider
from adlantis.observability import Tracer
from tests.fakes import (
    FakeLangfuse,
    anthropic_response,
    fake_anthropic_client,
    fake_openai_client,
    openai_response,
)

MODELS = ModelsConfig.model_validate(
    {
        "default": {"provider": "openai", "model": "gpt-default"},
        "roles": {
            "copywriter": {"provider": "anthropic", "model": "claude-copywriter"},
            "judge": {"provider": "openai", "model": "gpt-judge"},
            "strategist": {"provider": "openai", "model": "gpt-default"},
        },
        "pricing": {"claude-copywriter": {"input_per_mtok": 10, "output_per_mtok": 20}},
    }
)


class ClientFactory:
    """Hands out one fake client per provider and counts how often it's asked."""

    def __init__(self, openai_responses=(), anthropic_responses=()) -> None:
        self.clients = {
            "openai": fake_openai_client(*openai_responses),
            "anthropic": fake_anthropic_client(*anthropic_responses),
        }
        self.requests: list[str] = []

    def __call__(self, provider: str):
        self.requests.append(provider)
        return self.clients[provider]


def make_router(factory: ClientFactory, **kwargs) -> ModelRouter:
    return ModelRouter(Settings(), MODELS, client_factory=factory, **kwargs)


def test_routes_roles_to_mixed_providers() -> None:
    router = make_router(ClientFactory())
    copywriter, judge, strategist = (
        router.for_role(r) for r in ("copywriter", "judge", "strategist")
    )

    assert isinstance(copywriter, AnthropicProvider)
    assert copywriter.model == "claude-copywriter"
    assert isinstance(judge, OpenAIProvider)
    assert judge.model == "gpt-judge"
    assert strategist.model == "gpt-default"
    assert (copywriter.role, judge.role, strategist.role) == (
        "copywriter",
        "judge",
        "strategist",
    )


def test_providers_and_clients_are_cached() -> None:
    factory = ClientFactory()
    router = make_router(factory)
    assert router.for_role("judge") is router.for_role("JUDGE")
    router.for_role("strategist")
    router.for_role("copywriter")
    assert sorted(factory.requests) == ["anthropic", "openai"]  # one client per provider


def test_env_override_switches_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL__JUDGE", "anthropic:claude-judge")
    router = make_router(ClientFactory())
    judge = router.for_role("judge")
    assert isinstance(judge, AnthropicProvider)
    assert judge.model == "claude-judge"


def test_mixed_run_shares_usage_and_trace_tags_each_call() -> None:
    langfuse = FakeLangfuse()
    factory = ClientFactory(
        openai_responses=[openai_response("critique", input_tokens=7, output_tokens=3)],
        anthropic_responses=[anthropic_response("draft", input_tokens=100, output_tokens=50)],
    )
    router = make_router(factory, tracer=Tracer(langfuse))

    router.for_role("copywriter").complete([Message.user("write")])
    router.for_role("judge").complete([Message.user("review")])

    usage = router.usage
    assert usage.calls == 2
    assert usage.by_role["copywriter"].total_tokens == 150
    assert usage.by_role["judge"].total_tokens == 10
    assert usage.cost_usd == pytest.approx(100 * 10 / 1e6 + 50 * 20 / 1e6)
    tags = [
        (o.start_kwargs["metadata"]["role"], o.start_kwargs["metadata"]["provider"])
        for o in langfuse.observations
    ]
    assert tags == [("copywriter", "anthropic"), ("judge", "openai")]


def test_missing_key_for_used_provider_raises() -> None:
    router = ModelRouter(Settings(), MODELS)
    with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
        router.for_role("copywriter")


def test_key_only_needed_for_providers_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    router = ModelRouter(Settings(), MODELS)
    assert isinstance(router.for_role("judge"), OpenAIProvider)  # real SDK client, no call made


def test_from_settings_uses_custom_path(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    roles = {
        "researcher": "openai:r",
        "strategist": "openai:s",
        "copywriter": "openai:c",
        "claim_checker": "anthropic:custom",
        "designer": "openai:d",
        "judge": "openai:j",
    }
    lines = [
        f"  {r}: {{provider: {m.split(':')[0]}, model: {m.split(':')[1]}}}"
        for r, m in roles.items()
    ]
    path = tmp_path / "m.yaml"
    path.write_text("default: {provider: openai, model: c}\nroles:\n" + "\n".join(lines) + "\n")
    monkeypatch.setenv("MODELS_CONFIG_PATH", str(path))
    router = ModelRouter.from_settings(Settings())
    assert router.resolve("claim_checker").label == "anthropic:custom"


def test_misspelled_role_is_rejected_instead_of_using_the_default_model() -> None:
    with pytest.raises(ConfigurationError, match="Unknown role 'claim_cheker'"):
        make_router(ClientFactory()).for_role("claim_cheker")


def test_concurrent_requests_for_a_role_share_one_provider() -> None:
    router = make_router(ClientFactory())
    with ThreadPoolExecutor(max_workers=8) as pool:
        providers = list(pool.map(router.for_role, ["judge"] * 32))
    assert len({id(p) for p in providers}) == 1
