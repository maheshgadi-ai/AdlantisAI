from typer.testing import CliRunner

from adlantis import __version__
from adlantis.config import ROLES, Settings, load_profile
from adlantis.interfaces.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert (result.exit_code, result.output.strip()) == (0, __version__)


def test_config_defaults_to_the_budget_profile() -> None:
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0, result.output
    assert "profile: budget" in result.output
    for role in ROLES:
        assert load_profile("budget").resolve(role, Settings()).label in result.output


def test_config_rejects_an_unknown_profile() -> None:
    result = runner.invoke(app, ["config", "--profile", "premium"])
    assert result.exit_code == 1
    assert "Unknown profile" in result.output


def test_config_rejects_routing_that_breaks_the_rules(monkeypatch) -> None:
    monkeypatch.setenv("MODEL__CLAIM_CHECKER", "openai:gpt-6.2-sol")
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 1
    assert "different provider" in result.output
