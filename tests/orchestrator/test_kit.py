"""The packager ships only verified copy, and every claim shows its evidence."""

import hashlib
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from adlantis.orchestrator.kit_builder import build_baseline_kit
from adlantis.orchestrator.kit_store import (
    KitError,
    approve_kit,
    export_kit,
    find_run,
    load_kit,
    write_kit,
)
from adlantis.orchestrator.render_common import BASELINE_NOTICE, DRAFT_NOTICE, safe_url
from adlantis.orchestrator.render_html import render_html
from adlantis.orchestrator.render_markdown import render_markdown
from adlantis.rules.image_prompts import with_safety_suffix
from adlantis.schemas import AssetGap, ReviewOutcome, RuleViolation
from adlantis.schemas.design import DesignResult, GeneratedImage, ImagePrompt
from adlantis.schemas.kit import Approval, CampaignKit
from tests.orchestrator.kit_helpers import (
    COST,
    INPUTS,
    NOW,
    QUOTE,
    make_kit,
    reviewed,
    web_evidence,
)

LATER = datetime(2026, 11, 19, 9, 30, tzinfo=UTC)
PNG = b"png bytes"


def image(asset_id: str = "email-1", data: bytes = PNG) -> GeneratedImage:
    return GeneratedImage(
        asset_id=asset_id,
        file=f"images/{asset_id}.png",
        model="image-model",
        alt_text="A mug.",
        sha256=hashlib.sha256(data).hexdigest(),
    )


def prompt(asset_id: str = "email-1") -> ImagePrompt:
    return ImagePrompt(
        asset_id=asset_id,
        channel="email",
        prompt=with_safety_suffix("A mug."),
        alt_text="A mug.",
        size="1024x1024",
    )


def baseline_kit() -> CampaignKit:
    return build_baseline_kit(
        run_id="base",
        created_at=NOW,
        profile="budget",
        inputs=INPUTS,
        summary="One prompt.",
        assets=[reviewed()],
        cost=COST,
    )


def saved(tmp_path, kit=None):
    write_kit(kit or make_kit(), tmp_path)
    return tmp_path


def test_kit_starts_as_a_draft() -> None:
    kit = make_kit()
    assert (kit.status, kit.approval, kit.mode, kit.verified) == ("draft", None, "team", True)


def test_appendix_shows_the_approved_fact_behind_a_claim() -> None:
    claim = make_kit().claims[0]
    source = claim.sources[0]
    assert (claim.quote, claim.verdict) == (QUOTE, "supported")
    assert (source.reference, source.kind, source.text) == ("F-001", "fact", QUOTE)
    assert source.note and source.expires


def test_appendix_shows_the_link_behind_web_evidence() -> None:
    kit = make_kit(reviewed(references=["E-1"]), evidence=web_evidence())
    source = kit.claims[0].sources[0]
    assert (source.kind, source.url) == ("evidence", "https://publisher.example/report")
    assert source.title == "Coffee report"


def test_appendix_shows_a_glossary_definition() -> None:
    wording = INPUTS.brand.glossary[0].wording
    kit = make_kit(reviewed(references=[], quote=wording, supporting_passage=wording))
    assert [s.kind for s in kit.claims[0].sources] == ["glossary"]


@pytest.mark.parametrize("verdict", ["unsupported", "prohibited"])
def test_asset_with_a_blocked_claim_never_ships(verdict: str) -> None:
    kit = make_kit(reviewed(verdict=verdict))
    assert (kit.assets, kit.claims) == ([], [])
    assert kit.gaps[0].asset_id == "email-1"


def test_asset_with_a_blocking_rule_never_ships() -> None:
    item = reviewed()
    item.warnings.append(
        RuleViolation(rule="banned_word", asset_id="email-1", message="Banned.", fix="Remove.")
    )
    assert make_kit(item).assets == []


def test_warning_does_not_block_an_asset() -> None:
    item = reviewed()
    item.warnings.append(
        RuleViolation(
            rule="channel_limit",
            severity="warning",
            asset_id="email-1",
            message="Long.",
            fix="Trim.",
        )
    )
    assert len(make_kit(item).assets) == 1


@pytest.mark.parametrize("references", [[], ["F-999"], ["E-9"]])
def test_claim_without_a_traceable_source_never_ships(references: list[str]) -> None:
    kit = make_kit(reviewed(references=references))
    assert kit.assets == [] and "traceable" in kit.gaps[0].reason


def test_quarantined_evidence_is_not_a_source() -> None:
    store = web_evidence()
    store.records[0] = store.records[0].model_copy(update={"status": "quarantined"})
    assert make_kit(reviewed(references=["E-1"]), evidence=store).assets == []


def test_gaps_are_carried_without_copy() -> None:
    gap = AssetGap(asset_id="x-1", channel="x", reason="Failed review.")
    kit = make_kit(review=ReviewOutcome(gaps=[gap]))
    assert kit.gaps == [gap]
    assert "fields" not in kit.gaps[0].model_dump()


def test_images_and_prompts_of_removed_assets_are_dropped() -> None:
    kit = make_kit(
        reviewed(verdict="unsupported"),
        design=DesignResult(prompts=[prompt()]),
        images=[image()],
    )
    assert (kit.image_prompts, kit.images) == ([], [])


def test_approved_status_needs_a_recorded_sign_off() -> None:
    data = make_kit().model_dump() | {"status": "approved"}
    with pytest.raises(ValidationError, match="recorded sign-off"):
        CampaignKit.model_validate(data)


def test_hash_ignores_the_sign_off_but_not_the_content() -> None:
    kit = make_kit()
    approval = Approval(approved_by="A", approved_at=LATER, content_sha256="0" * 64)
    signed = kit.model_copy(update={"status": "approved", "approval": approval})
    edited = kit.model_copy(update={"product_name": "Other"})
    assert signed.compute_hash() == kit.compute_hash() != edited.compute_hash()


def test_markdown_has_copy_status_appendix_and_cost() -> None:
    text = render_markdown(make_kit())
    for part in (DRAFT_NOTICE, QUOTE, "## Claims appendix", "F-001", "$0.2000 of a $1.00 cap"):
        assert part in text


def test_markdown_links_web_sources_and_keeps_tables_whole() -> None:
    item = reviewed(references=["E-1"], quote="A | B\nC")
    text = render_markdown(make_kit(item, evidence=web_evidence()))
    assert "[Coffee report](<https://publisher.example/report>)" in text
    assert "A \\| B C" in text


def test_html_is_standalone_and_locked_down() -> None:
    page = render_html(make_kit())
    assert "default-src 'none'" in page
    assert "<script" not in page and "http://" not in page and 'src="http' not in page


def test_html_escapes_everything_from_models_and_the_web() -> None:
    attack = "<script>alert(1)</script>"
    item = reviewed(quote=attack)
    item.asset.fields["body"] = attack
    page = render_html(make_kit(item))
    assert attack not in page and "&lt;script&gt;" in page


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "https://a.example/x onclick=y",
        "//a.example",
        "https:///no-host",
    ],
)
def test_unsafe_links_are_never_rendered(url: str) -> None:
    assert safe_url(url) == ""
    kit = make_kit(reviewed(references=["E-1"]), evidence=web_evidence(url))
    assert "<a href" not in render_html(kit)
    assert "](<" not in render_markdown(kit)


def test_web_links_are_kept() -> None:
    assert safe_url("https://a.example/report?x=1") == "https://a.example/report?x=1"


def test_generated_images_are_labeled_in_every_format(tmp_path) -> None:
    kit = make_kit(design=DesignResult(prompts=[prompt()]), images=[image()])
    page = render_html(kit, {"images/email-1.png": PNG})
    assert "AI-generated image" in page and "data:image/png;base64" in page
    assert "AI-generated image" in render_markdown(kit)
    assert kit.images[0].model_dump()["label"] == "AI-generated image"


def test_image_label_cannot_be_changed() -> None:
    with pytest.raises(ValidationError):
        GeneratedImage.model_validate(image().model_dump() | {"label": "Photo"})


@pytest.mark.parametrize("file", ["../secret.png", "/etc/x.png", "images/a/b.png", "images/a.svg"])
def test_image_files_stay_in_the_kit_folder(file: str) -> None:
    with pytest.raises(ValidationError):
        GeneratedImage.model_validate(image().model_dump() | {"file": file})


def test_baseline_is_marked_unverified_everywhere() -> None:
    kit = baseline_kit()
    assert (kit.mode, kit.verified) == ("baseline", False)
    assert BASELINE_NOTICE in render_markdown(kit) and BASELINE_NOTICE in render_html(kit)
    assert "were not verified" in render_markdown(kit)


def test_all_three_formats_are_written_and_reload_identically(tmp_path) -> None:
    kit = make_kit()
    saved(tmp_path, kit)
    assert {p.name for p in tmp_path.iterdir()} == {"kit.json", "kit.md", "kit.html"}
    loaded = load_kit(tmp_path)
    assert loaded == kit and loaded.compute_hash() == kit.content_sha256


def test_missing_kit_is_reported(tmp_path) -> None:
    with pytest.raises(KitError, match="No kit found"):
        load_kit(tmp_path)


def test_invalid_kit_is_reported(tmp_path) -> None:
    (tmp_path / "kit.json").write_text("{}")
    with pytest.raises(KitError, match="invalid"):
        load_kit(tmp_path)


def test_runs_are_found_by_path_or_name(tmp_path) -> None:
    run = saved(tmp_path / "run-1")
    assert find_run(str(run), tmp_path / "other") == run
    assert find_run("run-1", tmp_path).resolve() == run.resolve()
    with pytest.raises(KitError, match="No run named"):
        find_run("run-2", tmp_path)


@pytest.mark.parametrize("fmt", ["md", "html", "json"])
def test_export_writes_the_chosen_format(tmp_path, fmt: str) -> None:
    run = saved(tmp_path / "run")
    path = export_kit(run, fmt, tmp_path / "out" / f"copy.{fmt}")
    assert path.read_text()


def test_approval_records_who_when_and_what(tmp_path) -> None:
    run = saved(tmp_path)
    kit = approve_kit(run, " Avery Lund ", LATER)
    assert (kit.status, kit.approval.approved_by) == ("approved", "Avery Lund")
    assert kit.approval.approved_at == LATER
    assert kit.approval.content_sha256 == kit.content_sha256
    assert load_kit(run).status == "approved"
    assert "Approved by Avery Lund" in (run / "kit.md").read_text()
    assert "Approved by Avery Lund" in (run / "kit.html").read_text()


def test_approval_needs_a_name(tmp_path) -> None:
    with pytest.raises(KitError, match="name of the person"):
        approve_kit(saved(tmp_path), "  ", LATER)
    assert load_kit(tmp_path).status == "draft"


def test_kit_cannot_be_approved_twice(tmp_path) -> None:
    approve_kit(saved(tmp_path), "A", LATER)
    with pytest.raises(KitError, match="already approved"):
        approve_kit(tmp_path, "B", LATER)
    assert load_kit(tmp_path).approval.approved_by == "A"


def test_baseline_cannot_be_approved(tmp_path) -> None:
    with pytest.raises(KitError, match="baseline"):
        approve_kit(saved(tmp_path, baseline_kit()), "A", LATER)


def test_empty_kit_cannot_be_approved(tmp_path) -> None:
    kit = make_kit(reviewed(verdict="unsupported"))
    with pytest.raises(KitError, match="no assets"):
        approve_kit(saved(tmp_path, kit), "A", LATER)


def test_edited_kit_cannot_be_approved(tmp_path) -> None:
    saved(tmp_path)
    path = tmp_path / "kit.json"
    data = json.loads(path.read_text())
    data["assets"][0]["asset"]["fields"]["body"] = "The best coffee in the world."
    path.write_text(json.dumps(data))
    with pytest.raises(KitError, match="changed after it was packaged"):
        approve_kit(tmp_path, "A", LATER)


def test_kit_with_an_unsupported_claim_cannot_be_approved(tmp_path) -> None:
    saved(tmp_path)
    path = tmp_path / "kit.json"
    data = json.loads(path.read_text())
    data["claims"][0]["verdict"] = "unsupported"
    path.write_text(json.dumps(data))
    with pytest.raises(KitError, match="not supported"):
        approve_kit(tmp_path, "A", LATER)


def test_swapped_image_cannot_be_approved(tmp_path) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "email-1.png").write_bytes(b"different")
    with pytest.raises(KitError, match="missing or changed"):
        approve_kit(saved(tmp_path, make_kit(images=[image()])), "A", LATER)


def test_missing_image_cannot_be_approved(tmp_path) -> None:
    with pytest.raises(KitError, match="missing or changed"):
        approve_kit(saved(tmp_path, make_kit(images=[image()])), "A", LATER)


def test_matching_image_can_be_approved(tmp_path) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "email-1.png").write_bytes(PNG)
    assert approve_kit(saved(tmp_path, make_kit(images=[image()])), "A", LATER).approval
