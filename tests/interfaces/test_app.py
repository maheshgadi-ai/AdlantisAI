"""The Streamlit app, driven headlessly. No test here calls a model."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import adlantis.interfaces.cli as cli
import adlantis.orchestrator.runner as runner_module
from adlantis.config import get_settings
from adlantis.interfaces.app_support import (
    claim_rows,
    example_text,
    gap_rows,
    ledger_rows,
    list_runs,
    missing_keys,
    parse_inputs,
    sample_campaign_dir,
)
from adlantis.orchestrator.kit_store import load_kit, write_kit
from adlantis.orchestrator.run_log import RunEvent
from adlantis.orchestrator.runner import RunOutput
from adlantis.schemas.inputs import InputFileError
from tests.orchestrator.kit_helpers import NOW, make_kit

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "src" / "adlantis" / "interfaces" / "app.py"


def app(monkeypatch, tmp_path, demo: bool = False, keys: bool = False) -> AppTest:
    monkeypatch.setenv("ADLANTIS_OUTPUTS", str(tmp_path / "outputs"))
    if demo:
        monkeypatch.setenv("ADLANTIS_DEMO", "1")
    else:
        monkeypatch.delenv("ADLANTIS_DEMO", raising=False)
    if keys:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    get_settings.cache_clear()
    return AppTest.from_file(str(APP), default_timeout=60).run()


def texts(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [m.value for m in at.caption]
    parts += [m.value for m in at.success] + [m.value for m in at.warning]
    parts += [m.value for m in at.info] + [m.value for m in at.error]
    return "\n".join(str(part) for part in parts)


def saved_draft(tmp_path: Path) -> Path:
    run = tmp_path / "outputs" / "20261119-120000-tamsin-hollow-roasters"
    write_kit(make_kit(), run)
    return run


def test_demo_opens_the_approved_sample_without_keys(monkeypatch, tmp_path) -> None:
    at = app(monkeypatch, tmp_path, demo=True)
    assert not at.exception
    kit = load_kit(sample_campaign_dir())
    assert "Approved by" in at.success[0].value
    assert len(at.tabs) == 7
    assert len(at.dataframe[0].value) == len(kit.claims)
    assert "No API keys are needed" in at.sidebar.info[0].value


def test_demo_offers_no_campaign_form_and_no_sign_off(monkeypatch, tmp_path) -> None:
    at = app(monkeypatch, tmp_path, demo=True)
    assert len(at.sidebar.radio) == 0
    assert not [b for b in at.button if b.label == "Approve kit"]


def test_demo_shows_the_channel_plan_label(monkeypatch, tmp_path) -> None:
    at = app(monkeypatch, tmp_path, demo=True)
    assert "Internal planning, not for publication." in texts(at)


def test_demo_offers_every_export(monkeypatch, tmp_path) -> None:
    at = app(monkeypatch, tmp_path, demo=True)
    labels = {element.proto.label for element in at.get("download_button")}
    assert labels == {"Download Markdown", "Download HTML", "Download JSON"}


def test_saved_draft_can_be_approved_by_a_person(monkeypatch, tmp_path) -> None:
    run = saved_draft(tmp_path)
    at = app(monkeypatch, tmp_path)
    assert "Draft." in at.warning[0].value
    button = next(b for b in at.button if b.label == "Approve kit")
    assert button.disabled
    at.text_input(key="approver").input("Avery Lund")
    at.text_input(key="confirm_run").input(run.name).run()
    next(b for b in at.button if b.label == "Approve kit").click().run()
    assert load_kit(run).approval.approved_by == "Avery Lund"


def test_approval_stays_locked_until_the_run_name_matches(monkeypatch, tmp_path) -> None:
    saved_draft(tmp_path)
    at = app(monkeypatch, tmp_path)
    at.text_input(key="approver").input("Avery Lund")
    at.text_input(key="confirm_run").input("wrong").run()
    assert next(b for b in at.button if b.label == "Approve kit").disabled


def test_new_campaign_without_keys_cannot_start(monkeypatch, tmp_path) -> None:
    at = app(monkeypatch, tmp_path)
    at.sidebar.radio[0].set_value("New campaign").run()
    assert "OPENAI_API_KEY" in texts(at) and "Estimated cost" in texts(at)
    assert next(b for b in at.button if b.label == "Start campaign").disabled


def test_new_campaign_needs_the_cost_accepted(monkeypatch, tmp_path) -> None:
    at = app(monkeypatch, tmp_path, keys=True)
    at.sidebar.radio[0].set_value("New campaign").run()
    assert next(b for b in at.button if b.label == "Start campaign").disabled


def test_invalid_inputs_are_reported(monkeypatch, tmp_path) -> None:
    at = app(monkeypatch, tmp_path)
    at.sidebar.radio[0].set_value("New campaign").run()
    at.text_area[0].input("name: [unclosed").run()
    assert "not valid" in at.error[0].value


def test_campaign_runs_with_a_live_timeline_and_opens_its_kit(monkeypatch, tmp_path) -> None:
    def fake_start(request, _settings, deps):
        deps.on_event(RunEvent(at=NOW, stage="research", status="started"))
        deps.on_event(RunEvent(at=NOW, stage="run", status="finished", detail="1 assets"))
        run_dir = request.outputs_dir / "20261119-130000-tamsin-hollow-roasters"
        write_kit(make_kit(), run_dir)
        return RunOutput(run_dir, load_kit(run_dir))

    monkeypatch.setattr(runner_module, "start_run", fake_start)
    at = app(monkeypatch, tmp_path, keys=True)
    at.sidebar.radio[0].set_value("New campaign").run()
    at.checkbox[0].check().run()
    next(b for b in at.button if b.label == "Start campaign").click().run()
    assert not at.exception
    assert list_runs(tmp_path / "outputs")[0].name == "20261119-130000-tamsin-hollow-roasters"


def test_sample_campaign_is_found_and_approved() -> None:
    assert load_kit(sample_campaign_dir()).status == "approved"


def test_example_inputs_parse() -> None:
    text = example_text()
    assert parse_inputs(text["brand"], text["facts"], text["product"]).product.name


def test_broken_input_is_an_input_error() -> None:
    with pytest.raises(InputFileError):
        parse_inputs("name: x", "facts: []", "{}")


def test_missing_keys_name_each_provider(monkeypatch) -> None:
    from adlantis.config import Settings

    settings = Settings(_env_file=None, openai_api_key="k")
    assert missing_keys(settings, "budget") == ["ANTHROPIC_API_KEY"]
    assert missing_keys(settings, "budget", baseline=True) == []


def test_tables_cover_claims_ledger_and_gaps() -> None:
    kit = load_kit(sample_campaign_dir())
    assert len(claim_rows(kit)) == len(kit.claims)
    assert len(ledger_rows(kit)) == len(kit.ledger.issues)
    assert any("image prompt" in row["Item"] for row in gap_rows(kit))


def test_runs_are_listed_newest_first(tmp_path) -> None:
    for name in ("20261118-a", "20261119-b"):
        write_kit(make_kit(), tmp_path / name)
    (tmp_path / "no-kit").mkdir()
    assert [p.name for p in list_runs(tmp_path)] == ["20261119-b", "20261118-a"]
    assert list_runs(tmp_path / "missing") == []


runner = CliRunner()


def test_demo_command_starts_the_app_in_demo_mode(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda cmd, env, check: calls.append((cmd, env)) or type("R", (), {"returncode": 0})(),
    )
    result = runner.invoke(cli.app, ["demo", "--headless", "--address", "0.0.0.0"])
    assert result.exit_code == 0, result.output
    command, env = calls[0]
    assert command[1:4] == ["-m", "streamlit", "run"] and command[4].endswith("app.py")
    assert "0.0.0.0" in command and env["ADLANTIS_DEMO"] == "1"


def test_app_command_starts_the_full_app_on_localhost(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda cmd, env, check: calls.append((cmd, env)) or type("R", (), {"returncode": 0})(),
    )
    assert runner.invoke(cli.app, ["app"]).exit_code == 0
    command, env = calls[0]
    assert "127.0.0.1" in command and "ADLANTIS_DEMO" not in env


def test_app_needs_the_ui_extra(monkeypatch) -> None:
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda _name: None)
    result = runner.invoke(cli.app, ["demo"])
    assert result.exit_code == 1 and "pip install 'adlantis[ui]'" in result.output
