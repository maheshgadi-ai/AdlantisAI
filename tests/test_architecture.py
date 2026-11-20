"""Enforce the layering rule: imports inside `adlantis` only flow downward."""

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "adlantis"

# Higher layers may import lower ones; same-rank packages may not import each other.
LAYER = {
    "config": 0,
    "schemas": 0,
    "prompts": 0,
    "observability": 1,
    "llm": 2,
    "tools": 2,
    "rules": 2,  # deterministic checks: no models, no network, no clock
    "agents": 3,
    "orchestrator": 4,
    "evals": 5,  # runs whole campaigns through the orchestrator
    "interfaces": 6,
}
MODEL_SDKS = ("openai", "anthropic")
MODEL_ID = re.compile(r"\b(?:gpt-\d|claude-(?:opus|sonnet|haiku|fable|mythos)|o[134]-mini)")


def _package(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "adlantis" else None


def _absolute(path: Path, node: ast.ImportFrom) -> str:
    """The absolute module a relative import refers to, so `from ..llm import x` is checked."""
    base = ("adlantis", *path.relative_to(SRC).parent.parts)
    kept = base[: len(base) - node.level + 1]
    return ".".join([*kept, *([node.module] if node.module else [])])


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            module = _absolute(path, node) if node.level else node.module
            if module:
                found.add(module)
                found |= {f"{module}.{alias.name}" for alias in node.names}
    return found


def _violations() -> list[str]:
    bad = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        if len(rel.parts) < 2:
            assert rel.name == "__init__.py", f"{rel} must live inside a layer package"
            continue
        src_pkg = rel.parts[0]
        assert src_pkg in LAYER, f"Add package '{src_pkg}' to LAYER in this test"
        for module in _imports(path):
            target = _package(module)
            if target in LAYER and target != src_pkg and LAYER[target] >= LAYER[src_pkg]:
                bad.append(f"{rel} imports {module}")
    return bad


def test_every_layer_package_exists() -> None:
    assert {p.name for p in SRC.iterdir() if (p / "__init__.py").is_file()} == set(LAYER)


def test_imports_only_flow_downward() -> None:
    assert _violations() == []


def test_tools_never_call_models() -> None:
    for path in (SRC / "tools").rglob("*.py"):
        imports = _imports(path)
        assert not any(m.startswith("adlantis.llm") for m in imports), path
        assert not any(m.split(".")[0] in MODEL_SDKS for m in imports), path


def test_rules_are_deterministic() -> None:
    """The rules engine never reaches a model, the network, or the system clock."""
    forbidden = (*MODEL_SDKS, "httpx", "httpx2", "requests", "socket", "urllib", "random", "time")
    for path in (SRC / "rules").rglob("*.py"):
        imports = _imports(path)
        assert not any(m.split(".")[0] in forbidden for m in imports), path
        assert not any(m.startswith(("adlantis.llm", "adlantis.tools")) for m in imports), path
        source = path.read_text()
        assert ".today()" not in source and ".now(" not in source, path


def test_research_code_cannot_reach_the_fact_sheet_or_brand_rules() -> None:
    """Web content flows through these modules, so they never see what it might try to change."""
    modules = [
        "agents/researcher.py",
        "tools/research_session.py",
        "tools/grounding.py",
        "tools/untrusted.py",
    ]
    forbidden = ("adlantis.schemas.facts", "adlantis.schemas.brand", "adlantis.schemas.inputs")
    for module in modules:
        assert not any(m.startswith(forbidden) for m in _imports(SRC / module)), module


def test_only_the_llm_layer_imports_provider_sdks() -> None:
    for path in SRC.rglob("*.py"):
        if path.relative_to(SRC).parts[0] != "llm":
            assert not any(m.split(".")[0] in MODEL_SDKS for m in _imports(path)), path


def test_agents_never_import_each_other() -> None:
    """Only the orchestrator wires agents together; agents may share `agents.base` only."""
    for path in (SRC / "agents").rglob("*.py"):
        if path.name == "__init__.py":
            continue
        siblings = {
            m
            for m in _imports(path)
            if m.startswith("adlantis.agents.") and not m.startswith("adlantis.agents.base")
        }
        assert not siblings, f"{path.name} imports {siblings}"


def test_model_ids_live_only_in_config() -> None:
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*")
        if path.suffix in {".py", ".md"}
        and path.relative_to(SRC).parts[0] != "config"
        and MODEL_ID.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_modules_stay_small() -> None:
    long = [
        str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if len(p.read_text().splitlines()) > 300
    ]
    assert long == []


def test_only_people_facing_interfaces_can_approve_a_kit() -> None:
    """No agent, tool, or pipeline step can reach the sign-off."""
    users = {
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if "approve_kit" in path.read_text(encoding="utf-8")
    }
    assert users == {"orchestrator/kit_store.py", "interfaces/cli.py", "interfaces/app.py"}


def test_lower_layers_cannot_import_the_kit_store() -> None:
    for package in ("agents", "tools", "llm", "rules"):
        for path in (SRC / package).rglob("*.py"):
            assert not any("kit_store" in module for module in _imports(path)), path
