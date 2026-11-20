"""The `adlantis` command line."""

from __future__ import annotations

import getpass
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from adlantis import __version__
from adlantis.config import (
    DEFAULT_PROFILE,
    PROFILES,
    ROLES,
    ConfigurationError,
    enforce_role_rules,
    get_settings,
    load_profile,
)
from adlantis.interfaces.app_support import missing_keys
from adlantis.interfaces.eval_cli import eval_app
from adlantis.orchestrator.kit_store import (
    ExportFormat,
    KitError,
    approve_kit,
    export_kit,
    find_run,
    load_kit,
)
from adlantis.orchestrator.run_log import utc_now
from adlantis.orchestrator.runner import RunFailed, RunRequest, estimate_run, start_run
from adlantis.schemas.inputs import InputFileError, load_campaign_inputs

app = typer.Typer(help="Marketing campaigns where every claim is traceable.", no_args_is_help=True)
app.add_typer(eval_app, name="eval")


def _show_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    _version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    """Marketing campaigns where every claim is traceable."""


@app.command()
def config(
    profile: Annotated[
        str, typer.Option(help=f"Routing profile: {', '.join(PROFILES)}.")
    ] = DEFAULT_PROFILE,
) -> None:
    """Show which model serves each role, after environment overrides."""
    settings = get_settings()
    try:
        models = load_profile(profile)
        enforce_role_rules(models, settings)
    except ConfigurationError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"profile: {profile}")
    for role in ROLES:
        spec = models.resolve(role, settings)
        typer.echo(f"{role:<14} {spec.label} (effort: {spec.reasoning_effort or 'default'})")


def _fail(message: str) -> typer.Exit:
    typer.echo(f"Error: {message}", err=True)
    return typer.Exit(code=1)


def _require_keys(settings, profile: str, baseline: bool) -> None:
    """Stop before any spending when a provider the run needs has no key."""
    missing = missing_keys(settings, profile, baseline)
    if missing:
        raise ConfigurationError(f"{', '.join(missing)} must be set before a run can start.")


def _launch(demo: bool, address: str, port: int, headless: bool, outputs: Path) -> None:
    if importlib.util.find_spec("streamlit") is None:
        raise _fail("The app needs the ui extra: pip install 'adlantis[ui]'")
    app_file = Path(__file__).with_name("app.py")
    command = [sys.executable, "-m", "streamlit", "run", str(app_file)]
    command += ["--server.address", address, "--server.port", str(port)]
    command += ["--server.headless", "true" if headless else "false"]
    command += ["--browser.gatherUsageStats", "false"]
    env = {**os.environ, "ADLANTIS_OUTPUTS": str(outputs.resolve())}
    if demo:
        env["ADLANTIS_DEMO"] = "1"
    raise typer.Exit(code=subprocess.run(command, env=env, check=False).returncode)


@app.command("app")
def app_command(
    address: Annotated[str, typer.Option(help="Address to listen on.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8501,
    headless: Annotated[bool, typer.Option(help="Do not open a browser.")] = False,
    outputs: Annotated[Path, typer.Option(help="Folder for run outputs.")] = Path("outputs"),
) -> None:
    """Open the app to run campaigns, review kits, and sign off."""
    _launch(False, address, port, headless, outputs)


@app.command()
def demo(
    address: Annotated[str, typer.Option(help="Address to listen on.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8501,
    headless: Annotated[bool, typer.Option(help="Do not open a browser.")] = False,
) -> None:
    """Open the approved sample campaign in the app. No API keys are needed."""
    _launch(True, address, port, headless, Path("outputs"))


@app.command()
def run(
    brand: Annotated[Path, typer.Option(help="Path to brand.yaml.")],
    facts: Annotated[Path, typer.Option(help="Path to facts.yaml.")],
    product: Annotated[Path, typer.Option(help="Path to product.yaml.")],
    baseline: Annotated[
        bool, typer.Option("--baseline", help="Write one unverified campaign for evaluation.")
    ] = False,
    profile: Annotated[
        str, typer.Option(help=f"Routing profile: {', '.join(PROFILES)}.")
    ] = DEFAULT_PROFILE,
    max_cost: Annotated[
        float, typer.Option("--max-cost", min=0.01, help="Hard spending cap in USD.")
    ] = 2.0,
    outputs: Annotated[Path, typer.Option(help="Folder for run outputs.")] = Path("outputs"),
    concurrency: Annotated[int, typer.Option(min=1, max=16, help="Agents working at once.")] = 4,
    yes: Annotated[bool, typer.Option("--yes", help="Start without asking to confirm.")] = False,
) -> None:
    """Build a campaign kit. It stays a draft until a person approves it."""
    settings = get_settings()
    try:
        inputs = load_campaign_inputs(brand, facts, product)
        _require_keys(settings, profile, baseline)
    except (InputFileError, ConfigurationError) as exc:
        raise _fail(str(exc)) from exc
    request = RunRequest(
        inputs=inputs,
        max_cost_usd=max_cost,
        profile=profile,
        baseline=baseline,
        outputs_dir=outputs,
        concurrency=concurrency,
    )
    estimate = estimate_run(request, settings)
    typer.echo(
        f"Estimated cost: about ${estimate.typical_usd:.2f}, at most "
        f"${estimate.worst_case_usd:.2f}. Hard cap: ${max_cost:.2f}."
    )
    if not yes and not typer.confirm("Start this billed run?"):
        typer.echo("Nothing was run.")
        raise typer.Exit
    try:
        output = start_run(request, settings)
    except RunFailed as exc:
        raise _fail(f"{exc} See {exc.run_dir / 'run_log.jsonl'}.") from exc
    kit = output.kit
    typer.echo(f"Run: {output.run_dir}")
    typer.echo(f"Status: {kit.status}. Assets: {len(kit.assets)}. Gaps: {len(kit.gaps)}.")
    typer.echo(f"Cost: ${kit.cost.total_usd:.4f}")


@app.command()
def approve(
    run_name: Annotated[str, typer.Argument(metavar="RUN", help="Run folder or its name.")],
    by: Annotated[str | None, typer.Option(help="Name of the person signing off.")] = None,
    outputs: Annotated[Path, typer.Option(help="Folder for run outputs.")] = Path("outputs"),
) -> None:
    """Record a person's sign-off on a draft kit."""
    try:
        run_dir = find_run(run_name, outputs)
        kit = load_kit(run_dir)
    except KitError as exc:
        raise _fail(str(exc)) from exc
    typer.echo(
        f"{kit.brand_name}: {kit.product_name}. {len(kit.assets)} assets, "
        f"{len(kit.claims)} claims, {len(kit.gaps)} gaps."
    )
    typed = typer.prompt(f"Type {run_dir.name} to approve this kit")
    if typed.strip() != run_dir.name:
        typer.echo("The name did not match. Nothing was approved.")
        raise typer.Exit(code=1)
    try:
        approved = approve_kit(run_dir, by or getpass.getuser(), utc_now())
    except KitError as exc:
        raise _fail(str(exc)) from exc
    typer.echo(f"Approved by {approved.approval.approved_by}.")


@app.command("export")
def export_command(
    run_name: Annotated[str, typer.Argument(metavar="RUN", help="Run folder or its name.")],
    fmt: Annotated[ExportFormat, typer.Option("--format", "-f", help="md, html, or json.")] = "md",
    out: Annotated[Path | None, typer.Option(help="Where to write the file.")] = None,
    outputs: Annotated[Path, typer.Option(help="Folder for run outputs.")] = Path("outputs"),
) -> None:
    """Export a saved kit as Markdown, HTML, or JSON."""
    try:
        path = export_kit(find_run(run_name, outputs), fmt, out)
    except KitError as exc:
        raise _fail(str(exc)) from exc
    typer.echo(str(path))
