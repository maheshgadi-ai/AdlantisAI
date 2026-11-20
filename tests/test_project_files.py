"""Repository rules: secrets stay out, required config stays in, and CI covers both Pythons."""

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ENV_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
REQUIRED_TRACKED = [
    ".env.example",
    ".github/workflows/ci.yml",
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "docs/decisions.md",
    "src/adlantis/config/models.yaml",
    "src/adlantis/config/models.budget.yaml",
    "src/adlantis/config/model_catalog.yaml",
    "src/adlantis/config/deprecated_models.yaml",
    "src/adlantis/config/source_quality.yaml",
    "evals/results/report.md",
    "examples/brand.yaml",
]
MUST_IGNORE = [
    ".env",
    ".env.local",
    "outputs/run/kit.json",
    ".streamlit/secrets.toml",
    "examples/sample-campaign/research.json",
]


def env_entries() -> dict[str, str]:
    lines = (ENV_LINE.match(x) for x in (ROOT / ".env.example").read_text().splitlines())
    return {m[1]: m[2] for m in lines if m}


def ignored(tmp_path: Path, paths: list[str]) -> set[str]:
    """Ask git itself, in a scratch repository, which paths the real .gitignore hides."""
    (tmp_path / ".gitignore").write_text((ROOT / ".gitignore").read_text())
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    done = subprocess.run(
        ["git", "check-ignore", "--no-index", *paths], cwd=tmp_path, capture_output=True, text=True
    )
    return set(done.stdout.split())


def test_env_example_has_only_blank_values() -> None:
    entries = env_entries()
    assert {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TAVILY_API_KEY"} <= set(entries)
    assert {k: v for k, v in entries.items() if v} == {}


def test_env_example_names_no_model_ids() -> None:
    assert not re.search(r"gpt-\d|claude-\w+-\d", (ROOT / ".env.example").read_text())


def test_gitignore_never_hides_required_config(tmp_path: Path) -> None:
    assert ignored(tmp_path, REQUIRED_TRACKED) == set()


def test_gitignore_hides_secrets_and_outputs(tmp_path: Path) -> None:
    assert ignored(tmp_path, MUST_IGNORE) == set(MUST_IGNORE)


def test_ci_lints_and_tests_on_both_python_versions() -> None:
    job = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]["lint-and-test"]
    assert job["strategy"]["matrix"]["python-version"] == ["3.11", "3.12"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    for command in ("ruff check .", "ruff format --check .", 'pytest -m "not live"'):
        assert command in commands


def test_project_metadata_names_the_author_and_license() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["authors"] == [{"name": "Venkata SatyaMahesh Gadi"}]
    assert project["license"] == "MIT"
    assert "Copyright (c) 2026 Venkata SatyaMahesh Gadi" in (ROOT / "LICENSE").read_text()


@pytest.mark.parametrize("name", ["openai", "anthropic", "httpx", "pyyaml", "typer"])
def test_directly_imported_packages_are_declared(name: str) -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert any(dep.startswith(name) for dep in project["dependencies"])
