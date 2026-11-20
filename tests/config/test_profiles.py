"""The shipped routing profiles and the rules every profile must satisfy."""

import pytest

from adlantis.config import (
    DEFAULT_PROFILE,
    PROFILES,
    ROLES,
    ConfigurationError,
    ModelsConfig,
    Settings,
    enforce_role_rules,
    load_models_config,
    load_profile,
    profile_path,
    role_rule_violations,
)
from adlantis.llm import ModelRouter

STRONG_TIER = 2
NAMES = list(PROFILES)


def specs(cfg: ModelsConfig) -> dict:
    return {role: cfg.resolve(role, Settings()) for role in ROLES}


def price(cfg: ModelsConfig, model: str) -> tuple[float, float]:
    known = cfg.price_for(model)
    return known.output_per_mtok, known.input_per_mtok


def test_budget_is_the_default_profile() -> None:
    assert DEFAULT_PROFILE == "budget"
    assert set(PROFILES) == {"default", "budget"}
    assert load_models_config().default == load_profile("budget").default


@pytest.mark.parametrize("name", NAMES)
def test_profile_configures_exactly_the_spec_roles(name: str) -> None:
    assert set(load_profile(name).roles) == set(ROLES)


@pytest.mark.parametrize("name", NAMES)
def test_claim_checker_uses_a_different_provider_than_the_copywriter(name: str) -> None:
    spec = specs(load_profile(name))
    assert spec["claim_checker"].provider != spec["copywriter"].provider


@pytest.mark.parametrize("name", NAMES)
def test_judge_is_a_different_model_from_those_it_grades(name: str) -> None:
    spec = specs(load_profile(name))
    assert spec["judge"].model not in {spec["copywriter"].model, spec["claim_checker"].model}


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("role", ["strategist", "copywriter", "claim_checker", "judge"])
def test_demanding_roles_use_strong_models(name: str, role: str) -> None:
    cfg = load_profile(name)
    assert cfg.capabilities[specs(cfg)[role].model].tier >= STRONG_TIER


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("role", ["researcher", "designer"])
def test_low_cost_roles_use_the_cheapest_catalog_model(name: str, role: str) -> None:
    cfg = load_profile(name)
    cheapest = min(price(cfg, model) for model in cfg.capabilities)
    assert price(cfg, specs(cfg)[role].model) == cheapest


@pytest.mark.parametrize("role", ROLES)
def test_budget_never_costs_more_than_default(role: str) -> None:
    budget, default = load_profile("budget"), load_profile("default")
    assert price(budget, specs(budget)[role].model) <= price(default, specs(default)[role].model)


@pytest.mark.parametrize("name", NAMES)
def test_every_routed_model_is_validated_and_priced(name: str) -> None:
    cfg = load_profile(name)
    for role in ["default", *ROLES]:
        model = cfg.resolve(role, Settings()).model
        assert cfg.capabilities_for(model), f"{model} has no capabilities entry"
        assert cfg.price_for(model).known, f"{model} has no price"


@pytest.mark.parametrize("name", NAMES)
def test_shipped_profiles_pass_the_runtime_rules(name: str) -> None:
    assert role_rule_violations(load_profile(name), Settings()) == []


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="Unknown profile 'premium'"):
        profile_path("premium")


def test_override_putting_checker_on_the_copywriter_provider_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL__CLAIM_CHECKER", "openai:gpt-6.2-sol")
    with pytest.raises(ConfigurationError, match="different provider"):
        enforce_role_rules(load_profile("budget"), Settings())


@pytest.mark.parametrize("graded", ["copywriter", "claim_checker"])
def test_override_making_the_judge_grade_itself_is_rejected(
    graded: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load_profile("budget")
    monkeypatch.setenv("MODEL__JUDGE", cfg.resolve(graded, Settings()).label)
    with pytest.raises(ConfigurationError, match=f"different model from {graded}"):
        enforce_role_rules(cfg, Settings())


def test_router_from_settings_enforces_the_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL__CLAIM_CHECKER", "openai:gpt-6.2-sol")
    with pytest.raises(ConfigurationError, match="different provider"):
        ModelRouter.from_settings(Settings())


def test_router_defaults_to_budget_and_accepts_a_named_profile() -> None:
    assert ModelRouter.from_settings(Settings()).models.roles == load_profile("budget").roles
    chosen = ModelRouter.from_settings(Settings(), profile="default")
    assert chosen.models.roles == load_profile("default").roles


def test_profile_missing_a_role_is_reported(tmp_path) -> None:
    path = tmp_path / "partial.yaml"
    path.write_text("default: {provider: openai, model: gpt-6.2-sol}\n")
    problems = role_rule_violations(load_models_config(path), Settings())
    assert "role 'claim_checker' is not configured" in problems
