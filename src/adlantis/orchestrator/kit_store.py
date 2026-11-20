"""Saves kits to disk, exports them, and records the human sign-off."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from adlantis.orchestrator.render_html import render_html
from adlantis.orchestrator.render_markdown import render_markdown
from adlantis.orchestrator.section_review import unverified_statements
from adlantis.schemas.kit import Approval, CampaignKit

KIT_FILE = "kit.json"
ExportFormat = Literal["md", "html", "json"]


class KitError(ValueError):
    """A kit cannot be found, read, exported, or approved."""


def _write_atomic(path: Path, text: str) -> None:
    """Replace a file in one step, so a crash never leaves half a kit."""
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        Path(name).replace(path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def _image_files(kit: CampaignKit, run_dir: Path) -> dict[str, bytes]:
    return {
        image.file: (run_dir / image.file).read_bytes()
        for image in kit.images
        if (run_dir / image.file).is_file()
    }


def render(kit: CampaignKit, run_dir: Path, fmt: ExportFormat) -> str:
    """The kit in one output format."""
    if fmt == "md":
        return render_markdown(kit)
    if fmt == "html":
        return render_html(kit, _image_files(kit, run_dir))
    return kit.model_dump_json(indent=2)


def write_kit(kit: CampaignKit, run_dir: Path) -> None:
    """Write the kit in all three formats."""
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(run_dir / "kit.md", render(kit, run_dir, "md"))
    _write_atomic(run_dir / "kit.html", render(kit, run_dir, "html"))
    _write_atomic(run_dir / KIT_FILE, render(kit, run_dir, "json"))


def load_kit(run_dir: Path) -> CampaignKit:
    """Read a saved kit.

    Raises:
        KitError: If the kit is missing or invalid.
    """
    try:
        return CampaignKit.model_validate_json((run_dir / KIT_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KitError(f"No kit found in {run_dir}.") from exc
    except ValidationError as exc:
        raise KitError(f"The kit in {run_dir} is invalid: {exc}") from exc


def find_run(run: str, outputs_dir: Path) -> Path:
    """Resolve a run given as a path or as a folder name under `outputs_dir`."""
    for candidate in (Path(run), outputs_dir / run):
        if (candidate / KIT_FILE).is_file():
            return candidate
    raise KitError(f"No run named {run!r} was found.")


def export_kit(run_dir: Path, fmt: ExportFormat, destination: Path | None = None) -> Path:
    """Write one format of a saved kit and return where it went."""
    kit = load_kit(run_dir)
    path = destination or run_dir / f"kit.{fmt}"
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, render(kit, run_dir, fmt))
    return path


def _refusal(kit: CampaignKit, run_dir: Path) -> str | None:
    if kit.mode == "baseline" or not kit.verified:
        return "A baseline kit is unverified and cannot be approved."
    if kit.status == "approved":
        return "This kit is already approved."
    if not kit.assets:
        return "This kit has no assets to approve."
    if any(claim.verdict != "supported" for claim in kit.claims):
        return "This kit contains a claim that is not supported."
    if unverified_statements(kit):
        return "A section of this kit did not pass verification."
    if kit.content_sha256 != kit.compute_hash():
        return "This kit changed after it was packaged, so it cannot be approved."
    for image in kit.images:
        path = run_dir / image.file
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != image.sha256:
            return f"Image {image.file} is missing or changed after it was packaged."
    return None


def approve_kit(run_dir: Path, approved_by: str, approved_at: datetime) -> CampaignKit:
    """Move a draft kit to approved, recording who approved it and when.

    Only the human-facing interfaces call this. No agent or tool can reach it.

    Raises:
        KitError: If the kit cannot be approved.
    """
    name = approved_by.strip()
    if not name:
        raise KitError("Approval needs the name of the person signing off.")
    kit = load_kit(run_dir)
    refusal = _refusal(kit, run_dir)
    if refusal:
        raise KitError(refusal)
    approval = Approval(
        approved_by=name, approved_at=approved_at, content_sha256=kit.content_sha256
    )
    approved = kit.model_copy(update={"status": "approved", "approval": approval})
    write_kit(approved, run_dir)
    return approved
