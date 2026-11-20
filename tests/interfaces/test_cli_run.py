"""The command line shows the cost first and leaves approval to a person."""

from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

import adlantis.interfaces.cli as cli
from adlantis.config import Settings
from adlantis.orchestrator.kit_store import load_kit, write_kit
from adlantis.orchestrator.runner import RunFailed, RunOutput
from tests.orchestrator.kit_helpers import EXAMPLE, make_kit

runner = CliRunner()
FILES = [
    "--brand",
    str(EXAMPLE / "brand.yaml"),
    "--facts",
    str(EXAMPLE / "facts.yaml"),
    "--product",
    str(EXAMPLE / "product.yaml"),
]


@pytest.fixture
def keys(monkeypatch):
    settings = Settings(
        _env_file=None, openai_api_key=SecretStr("test"), anthropic_api_key=SecretStr("test")
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def started(monkeypatch, tmp_path):
    calls = []

    def fake_start(request, _settings):
        calls.append(request)
        return RunOutput(tmp_path / "run", make_kit())

    monkeypatch.setattr(cli, "start_run", fake_start)
    return calls


def saved_run(tmp_path: Path) -> Path:
    run = tmp_path / "run-1"
    write_kit(make_kit(), run)
    return run


def test_run_shows_the_estimate_and_stops_when_declined(keys, started) -> None:
    result = runner.invoke(cli.app, ["run", *FILES], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Estimated cost" in result.output and "Hard cap: $2.00" in result.output
    assert "Nothing was run." in result.output
    assert started == []


def test_run_starts_after_confirmation(keys, started) -> None:
    result = runner.invoke(cli.app, ["run", *FILES, "--max-cost", "1.5"], input="y\n")
    assert result.exit_code == 0, result.output
    assert started[0].max_cost_usd == 1.5
    assert (started[0].profile, started[0].baseline) == ("budget", False)
    assert "Status: draft" in result.output


def test_run_options_reach_the_request(keys, started) -> None:
    args = ["run", *FILES, "--baseline", "--profile", "default", "--concurrency", "2", "--yes"]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert (started[0].baseline, started[0].profile, started[0].concurrency) == (True, "default", 2)


def test_zero_cap_is_refused(keys, started) -> None:
    assert runner.invoke(cli.app, ["run", *FILES, "--max-cost", "0"]).exit_code != 0
    assert started == []


def test_missing_key_stops_before_any_spending(monkeypatch, started) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    result = runner.invoke(cli.app, ["run", *FILES, "--yes"])
    assert result.exit_code == 1
    assert "API_KEY must be set" in result.output
    assert started == []


def test_baseline_needs_only_the_copywriters_key(monkeypatch, started) -> None:
    settings = Settings(_env_file=None, openai_api_key=SecretStr("test"))
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert runner.invoke(cli.app, ["run", *FILES, "--baseline", "--yes"]).exit_code == 0


def test_invalid_input_file_is_reported(keys, started, tmp_path) -> None:
    args = ["run", "--brand", str(tmp_path / "no.yaml"), *FILES[2:], "--yes"]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 1 and "not found" in result.output


def test_failed_run_points_to_its_log(keys, monkeypatch, tmp_path) -> None:
    def fail(_request, _settings):
        raise RunFailed("No strategy could be produced.", tmp_path)

    monkeypatch.setattr(cli, "start_run", fail)
    result = runner.invoke(cli.app, ["run", *FILES, "--yes"])
    assert result.exit_code == 1 and "run_log.jsonl" in result.output


def test_approve_requires_typing_the_run_name(tmp_path) -> None:
    run = saved_run(tmp_path)
    args = ["approve", "run-1", "--outputs", str(tmp_path), "--by", "Avery"]
    result = runner.invoke(cli.app, args, input="yes\n")
    assert result.exit_code == 1 and "Nothing was approved" in result.output
    assert load_kit(run).status == "draft"


def test_approve_records_the_person(tmp_path) -> None:
    run = saved_run(tmp_path)
    args = ["approve", "run-1", "--outputs", str(tmp_path), "--by", "Avery"]
    result = runner.invoke(cli.app, args, input="run-1\n")
    assert result.exit_code == 0, result.output
    assert load_kit(run).approval.approved_by == "Avery"


def test_approve_has_no_way_to_skip_the_prompt() -> None:
    params = next(
        c for c in cli.app.registered_commands if c.name is None and c.callback == cli.approve
    )
    assert "yes" not in params.callback.__annotations__


def test_approve_reports_an_unknown_run(tmp_path) -> None:
    result = runner.invoke(cli.app, ["approve", "nope", "--outputs", str(tmp_path)])
    assert result.exit_code == 1 and "No run named" in result.output


def test_approving_twice_is_an_error(tmp_path) -> None:
    saved_run(tmp_path)
    args = ["approve", "run-1", "--outputs", str(tmp_path), "--by", "Avery"]
    runner.invoke(cli.app, args, input="run-1\n")
    assert runner.invoke(cli.app, args, input="run-1\n").exit_code == 1


@pytest.mark.parametrize("fmt", ["md", "html", "json"])
def test_export_writes_each_format(tmp_path, fmt: str) -> None:
    run = saved_run(tmp_path)
    result = runner.invoke(cli.app, ["export", "run-1", "-f", fmt, "--outputs", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (run / f"kit.{fmt}").is_file()


def test_export_rejects_an_unknown_format(tmp_path) -> None:
    saved_run(tmp_path)
    args = ["export", "run-1", "-f", "pdf", "--outputs", str(tmp_path)]
    assert runner.invoke(cli.app, args).exit_code != 0


def test_export_reports_an_unknown_run(tmp_path) -> None:
    assert runner.invoke(cli.app, ["export", "nope", "--outputs", str(tmp_path)]).exit_code == 1
