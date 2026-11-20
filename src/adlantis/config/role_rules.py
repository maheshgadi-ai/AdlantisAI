"""Routing rules every profile must satisfy, after environment overrides are applied.

The claim checker only adds independent assurance when it does not share a provider with the
copywriter, and the judge only gives a fair score when it is not grading its own output.
"""

from __future__ import annotations

from adlantis.config.models import ConfigurationError, ModelsConfig
from adlantis.config.settings import Settings

ROLES = ("researcher", "strategist", "copywriter", "claim_checker", "designer", "judge")


def role_rule_violations(models: ModelsConfig, settings: Settings) -> list[str]:
    """Return a readable description of each broken routing rule (empty when all hold)."""
    missing = sorted(set(ROLES) - set(models.roles))
    unknown = sorted(set(models.roles) - set(ROLES))
    problems = [f"role {role!r} is not configured" for role in missing]
    problems += [f"role {role!r} is not a known role" for role in unknown]
    if missing:
        return problems

    spec = {role: models.resolve(role, settings) for role in ROLES}
    copywriter, checker, judge = spec["copywriter"], spec["claim_checker"], spec["judge"]
    if checker.provider == copywriter.provider:
        problems.append(
            f"claim_checker ({checker.label}) must use a different provider "
            f"than copywriter ({copywriter.label})"
        )
    for graded in ("copywriter", "claim_checker"):
        if judge.model == spec[graded].model:
            problems.append(f"judge must be a different model from {graded} ({judge.model})")
    return problems


def enforce_role_rules(models: ModelsConfig, settings: Settings) -> None:
    """Raise `ConfigurationError` when the resolved routing breaks a rule."""
    problems = role_rule_violations(models, settings)
    if problems:
        raise ConfigurationError("Invalid model routing: " + "; ".join(problems))
