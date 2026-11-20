"""Plain functions behind the Streamlit app, kept separate so they can be tested directly."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml
from pydantic import ValidationError

from adlantis.config import Settings, enforce_role_rules, load_profile
from adlantis.orchestrator.kit_store import KIT_FILE, render
from adlantis.orchestrator.render_common import CHANNEL_TITLES, status_line
from adlantis.schemas.brand import BrandKit
from adlantis.schemas.facts import FactSheet
from adlantis.schemas.inputs import CampaignInputs, InputFileError
from adlantis.schemas.kit import CampaignKit, ClaimSource
from adlantis.schemas.product import ProductBrief

TEAM_ROLES = ("researcher", "strategist", "copywriter", "claim_checker", "designer")
SAMPLE_NAME = "sample-campaign"
_REPO_EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def examples_dir() -> Path:
    """The example brands and sample campaign, from the installed package or the source tree."""
    packaged = Path(str(resources.files("adlantis") / "examples"))
    for candidate in (packaged, _REPO_EXAMPLES, Path("examples")):
        if (candidate / SAMPLE_NAME / KIT_FILE).is_file():
            return candidate
    raise FileNotFoundError("The sample campaign is not available in this installation.")


def sample_campaign_dir() -> Path:
    """The approved sample campaign the demo opens."""
    return examples_dir() / SAMPLE_NAME


def missing_keys(settings: Settings, profile: str, baseline: bool = False) -> list[str]:
    """The API key settings a run on this profile still needs."""
    models = load_profile(profile)
    enforce_role_rules(models, settings)
    roles = ("copywriter",) if baseline else TEAM_ROLES
    providers = {models.resolve(role, settings).provider for role in roles}
    return [
        f"{provider.upper()}_API_KEY"
        for provider in sorted(providers)
        if not settings.api_key(provider)
    ]


def list_runs(outputs_dir: Path) -> list[Path]:
    """Saved runs with a kit, newest first."""
    if not outputs_dir.is_dir():
        return []
    runs = [path for path in outputs_dir.iterdir() if (path / KIT_FILE).is_file()]
    return sorted(runs, key=lambda path: path.name, reverse=True)


def example_text(brand: str = "tamsin-hollow-roasters") -> dict[str, str]:
    """The text of one example brand's three input files."""
    folder = examples_dir() / brand
    return {name: (folder / f"{name}.yaml").read_text(encoding="utf-8") for name in _INPUTS}


_INPUTS = ("brand", "facts", "product")


def parse_inputs(brand: str, facts: str, product: str) -> CampaignInputs:
    """Validate the three input files given as text.

    Raises:
        InputFileError: If any file is not valid YAML or does not match its schema.
    """
    try:
        return CampaignInputs(
            brand=BrandKit.model_validate(yaml.safe_load(brand)),
            facts=FactSheet.model_validate(yaml.safe_load(facts)),
            product=ProductBrief.model_validate(yaml.safe_load(product)),
        )
    except (yaml.YAMLError, ValidationError, TypeError) as exc:
        raise InputFileError(f"The inputs are not valid: {exc}") from exc


def status_text(kit: CampaignKit) -> str:
    """The kit's sign-off state as one sentence."""
    return status_line(kit)


def _source(source: ClaimSource) -> str:
    if source.kind == "evidence":
        return f"{source.reference}: {source.title} ({source.url})"
    if source.kind == "glossary":
        return f"glossary: {source.text}"
    return f"{source.reference}: {source.text}"


def claim_rows(kit: CampaignKit) -> list[dict[str, str]]:
    """The claims appendix as table rows."""
    return [
        {
            "Claim": claim.id,
            "Section": CHANNEL_TITLES.get(claim.channel, claim.channel),
            "Text": claim.quote,
            "Type": claim.claim_type,
            "Verdict": claim.verdict,
            "Evidence": "; ".join(_source(source) for source in claim.sources),
        }
        for claim in kit.claims
    ]


def ledger_rows(kit: CampaignKit) -> list[dict[str, str]]:
    """The issue ledger as table rows."""
    return [
        {
            "Issue": issue.id,
            "Asset": issue.asset_id,
            "Status": issue.status,
            "Problem": issue.problem,
            "History": "; ".join(issue.history),
        }
        for issue in kit.ledger.issues
    ]


def gap_rows(kit: CampaignKit) -> list[dict[str, str]]:
    """Removed work as table rows."""
    rows = [{"Item": gap.asset_id, "Reason": gap.reason} for gap in kit.gaps]
    rows += [
        {"Item": f"{prompt.asset_id} image prompt", "Reason": prompt.reason}
        for prompt in kit.rejected_image_prompts
    ]
    return rows


def warning_rows(kit: CampaignKit) -> list[dict[str, str]]:
    """Non-blocking warnings as table rows."""
    return [
        {"Asset": item.asset.asset_id, "Rule": warning.rule, "Message": warning.message}
        for item in kit.assets
        for warning in item.warnings
    ]


def assets_by_channel(kit: CampaignKit) -> dict[str, list]:
    """Shipped assets grouped under each channel's title."""
    grouped: dict[str, list] = {}
    for item in kit.assets:
        grouped.setdefault(CHANNEL_TITLES[item.asset.channel], []).append(item)
    return grouped


def downloads(kit: CampaignKit, run_dir: Path) -> list[tuple[str, str, str, str]]:
    """Each export as (label, content, file name, media type)."""
    return [
        ("Markdown", render(kit, run_dir, "md"), "kit.md", "text/markdown"),
        ("HTML", render(kit, run_dir, "html"), "kit.html", "text/html"),
        ("JSON", render(kit, run_dir, "json"), "kit.json", "application/json"),
    ]
