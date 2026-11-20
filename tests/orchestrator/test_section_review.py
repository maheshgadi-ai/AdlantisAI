"""Strategy statements and image prompts ship only when they pass verification."""

import asyncio
import json

import pytest

from adlantis.orchestrator.kit_builder import KitBlocked, build_team_kit, seal
from adlantis.orchestrator.kit_store import KitError, approve_kit, write_kit
from adlantis.orchestrator.pipeline import CampaignPipeline, PipelineError, PipelineOptions
from adlantis.orchestrator.policy import AgentPolicy
from adlantis.orchestrator.render_html import render_html
from adlantis.orchestrator.revision import apply_edits
from adlantis.orchestrator.run_log import RunLog
from adlantis.orchestrator.section_review import (
    image_sections,
    strategy_sections,
    unverified_statements,
)
from adlantis.rules import check_asset
from adlantis.rules.claim_gate import settle_claims
from adlantis.rules.image_prompts import with_safety_suffix
from adlantis.schemas import (
    AssetEdit,
    CampaignStrategy,
    DraftClaim,
    EvidenceStore,
    ReviewedAsset,
    RevisionPlan,
    RuleViolation,
    StrategyResult,
)
from adlantis.schemas.channels import SECTION_CHANNELS
from adlantis.schemas.design import DesignResult, ImagePrompt
from tests.orchestrator.kit_helpers import (
    INPUTS,
    NOW,
    TODAY,
    StubChecker,
    StubCopywriter,
    StubDesigner,
    StubStrategist,
    make_claim,
    make_kit,
    parts,
    reviewed,
    stub_team,
    verified_sections,
)

FALSE_LINE = "It tastes of red apple, panela, and cocoa, a light roast made for filter brewing."
TRUE_LINE = "It tastes of red apple, panela, and cocoa."
NO_RETRY = dict.fromkeys(
    ("researcher", "strategist", "copywriter", "claim_checker", "designer"),
    AgentPolicy(timeout_seconds=10, retries=0),
)


def strategy(*messages: str, **changes: object) -> CampaignStrategy:
    values = {
        "positioning": "Traceable coffee for home brewers.",
        "concept": "Know the farm, taste the cup.",
        "key_messages": [
            {"message": text, "references": ["F-003"]} for text in (messages or (TRUE_LINE,))
        ],
        "channel_mix": [
            {"channel": "email", "role": "Launch", "rationale": "Reaches subscribers."}
        ],
    }
    return CampaignStrategy.model_validate({**values, **changes})


class GateChecker:
    """A checker model that approves everything, so only the code gate can catch a false claim."""

    def __init__(self, ctx, evidence, bad: str = "light roast") -> None:
        self.ctx = ctx
        self.evidence = evidence
        self.bad = bad

    def run(self, asset):
        if asset.channel not in SECTION_CHANNELS:
            return StubChecker().run(asset)
        drafts = [
            DraftClaim(
                field=field,
                quote=text,
                claim_type="product_fact",
                references=["F-003"],
                verdict="supported",
                supporting_passage=text,
                reason="Looks right.",
            )
            for field, text in asset.fields.items()
            if self.bad in text
        ]
        return settle_claims(drafts, asset, self.ctx, self.evidence, check_asset(asset, self.ctx))


class TrimmingCopywriter(StubCopywriter):
    def revise(self, request) -> RevisionPlan:
        edit = AssetEdit(
            issue_id=request.issues[0].id,
            field="message",
            find=", a light roast made for filter brewing",
            replace="",
        )
        return RevisionPlan(edits=[edit])


def run(drafted: CampaignStrategy, copywriter=None, designer=None):
    team = stub_team(
        strategist=StubResearcherStrategy(drafted),
        copywriter=copywriter or StubCopywriter(),
        designer=designer or StubDesigner(),
        make_checker=GateChecker,
    )
    log = RunLog()
    options = PipelineOptions(today=TODAY, policies=NO_RETRY)
    return asyncio.run(CampaignPipeline(INPUTS, team, log, options).run()), log


class StubResearcherStrategy(StubStrategist):
    def __init__(self, drafted: CampaignStrategy, rejected: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.drafted = drafted
        self.rejected = rejected

    def run(self, _request) -> StrategyResult:
        return StrategyResult(strategy=self.drafted, rejected_messages=list(self.rejected))


def kit_from(result):
    review = result.review
    return build_team_kit(
        parts(
            *review.assets,
            review=review,
            strategy=result.strategy,
            sections=result.sections,
            design=result.design,
            extra_gaps=[*result.channel_gaps, *result.section_gaps],
        )
    )


def test_unproven_key_message_is_removed_and_reported() -> None:
    result, log = run(strategy(TRUE_LINE, FALSE_LINE))
    assert [m.message for m in result.strategy.key_messages] == [TRUE_LINE]
    gap = result.section_gaps[0]
    assert (gap.asset_id, gap.channel) == ("strategy-message-2", "strategy")
    assert "does not appear in the cited source" in gap.reason
    assert any(
        e.stage == "verify:strategy" and "strategy-message-2" in e.detail for e in log.events
    )


def test_unproven_line_never_reaches_the_kit() -> None:
    kit = kit_from(run(strategy(TRUE_LINE, FALSE_LINE))[0])
    assert "light roast" not in kit.strategy.model_dump_json()
    assert unverified_statements(kit) == []
    assert kit.gaps[0].asset_id == "strategy-message-2"


def test_copy_is_written_from_the_verified_strategy_only() -> None:
    seen = []

    class Recording(StubCopywriter):
        def run(self, request):
            seen.append(request.strategy)
            return super().run(request)

    run(strategy(TRUE_LINE, FALSE_LINE), Recording())
    assert all("light roast" not in item.model_dump_json() for item in seen)


def test_targeted_revision_can_save_a_key_message() -> None:
    result, _ = run(strategy(FALSE_LINE), TrimmingCopywriter())
    message = result.strategy.key_messages[0]
    assert (message.message, message.references) == (TRUE_LINE, ["F-003"])
    assert result.section_gaps == []
    assert result.review.ledger.issues[0].status == "resolved"


@pytest.mark.parametrize(
    "changes",
    [
        {"positioning": "A light roast for home brewers."},
        {"concept": "The light roast you want."},
    ],
)
def test_unproven_positioning_or_concept_stops_the_run(changes: dict) -> None:
    with pytest.raises(PipelineError, match="could not be verified"):
        run(strategy(**changes))


def test_no_verified_key_message_stops_the_run() -> None:
    with pytest.raises(PipelineError, match="No key message"):
        run(strategy(FALSE_LINE))


def test_no_verified_channel_plan_stops_the_run() -> None:
    plan = {"channel": "email", "role": "Launch", "rationale": "It is a light roast."}
    with pytest.raises(PipelineError, match="No channel plan"):
        run(strategy(channel_mix=[plan]))


def test_unproven_channel_plan_is_removed_and_reported() -> None:
    plans = [
        {"channel": "email", "role": "Launch", "rationale": "Reaches subscribers."},
        {"channel": "instagram", "role": "Reach", "rationale": "It is a light roast."},
    ]
    result, _ = run(strategy(channel_mix=plans))
    assert [p.channel for p in result.strategy.channel_mix] == ["email"]
    assert result.section_gaps[0].asset_id == "strategy-channel-instagram"


def test_messages_the_strategist_lost_are_reported_without_their_text() -> None:
    team = stub_team(strategist=StubResearcherStrategy(strategy(), ("Secret line.",)))
    options = PipelineOptions(today=TODAY, policies=NO_RETRY)
    result = asyncio.run(CampaignPipeline(INPUTS, team, RunLog(), options).run())
    assert result.section_gaps[0].asset_id == "strategy-rejected-1"
    assert "Secret line" not in result.section_gaps[0].reason


def test_unproven_image_prompt_is_dropped_with_its_reason() -> None:
    designer = StubDesigner(prompt=with_safety_suffix("A light roast in a mug."))
    result, _ = run(strategy(), designer=designer)
    assert result.design.prompts == []
    assert "does not appear in the cited source" in result.design.rejected[0].reason


def test_image_prompts_are_never_rewritten() -> None:
    class Failing(StubCopywriter):
        def revise(self, _request):
            raise AssertionError("image prompts are not revised")

    designer = StubDesigner(prompt=with_safety_suffix("A light roast in a mug."))
    assert run(strategy(), Failing(), designer)[0].design.prompts == []


def test_every_section_is_recorded_in_the_kit_and_its_appendix() -> None:
    kit = make_kit(
        sections=[
            ReviewedAsset(
                asset=item.asset,
                claims=[make_claim(item.asset.asset_id, field=next(iter(item.asset.fields)))],
            )
            for item in verified_sections()
        ]
    )
    assert {c.channel for c in kit.claims} == {"email", "strategy"}
    assert len(kit.verified_sections) == 4


@pytest.mark.parametrize("verdict", ["unsupported", "prohibited"])
def test_kit_cannot_be_built_with_a_failed_section(verdict: str) -> None:
    sections = verified_sections()
    sections[0] = ReviewedAsset(
        asset=sections[0].asset, claims=[make_claim(sections[0].asset.asset_id, verdict=verdict)]
    )
    with pytest.raises(KitBlocked, match="positioning"):
        make_kit(sections=sections)


def test_kit_cannot_be_built_with_a_missing_section() -> None:
    with pytest.raises(KitBlocked, match="key message"):
        make_kit(sections=[s for s in verified_sections() if "message" not in s.asset.fields])


def test_kit_cannot_be_built_with_an_untraceable_section_claim() -> None:
    sections = verified_sections()
    sections[0] = ReviewedAsset(
        asset=sections[0].asset, claims=[make_claim(sections[0].asset.asset_id, references=[])]
    )
    with pytest.raises(KitBlocked):
        make_kit(sections=sections)


def test_kit_cannot_be_built_with_an_unchecked_image_prompt() -> None:
    prompt = ImagePrompt(
        asset_id="email-1",
        channel="email",
        prompt=with_safety_suffix("A mug."),
        alt_text="A mug.",
        size="1024x1024",
    )
    with pytest.raises(KitBlocked, match="image prompt"):
        make_kit(design=DesignResult(prompts=[prompt]), sections=verified_sections())


def test_section_text_must_match_what_was_verified() -> None:
    edited = make_kit().strategy.model_copy(update={"concept": "Something unchecked."})
    with pytest.raises(KitBlocked, match="concept"):
        make_kit(strategy=edited, sections=verified_sections())


def test_edited_strategy_cannot_be_approved_even_with_a_matching_fingerprint(tmp_path) -> None:
    kit = make_kit()
    changed = kit.strategy.model_copy(update={"positioning": FALSE_LINE})
    write_kit(seal(kit.model_copy(update={"strategy": changed})), tmp_path)
    with pytest.raises(KitError, match="did not pass verification"):
        approve_kit(tmp_path, "Avery", NOW)


def test_verified_kit_can_be_approved(tmp_path) -> None:
    write_kit(make_kit(reviewed()), tmp_path)
    assert approve_kit(tmp_path, "Avery", NOW).status == "approved"


def test_sections_are_not_held_to_channel_limits() -> None:
    from tests.orchestrator.kit_helpers import STRATEGY

    section = strategy_sections(STRATEGY, INPUTS.facts, TODAY)[0]
    long = section.model_copy(update={"fields": {"positioning": "Plain words. " * 40}})
    ctx = GateContext.make()
    assert check_asset(long, ctx).violations == []


def test_rules_engine_still_runs_on_sections() -> None:
    from tests.orchestrator.kit_helpers import STRATEGY

    section = strategy_sections(STRATEGY, INPUTS.facts, TODAY)[0]
    bad = section.model_copy(update={"fields": {"positioning": "A miracle roast."}})
    assert {v.rule for v in check_asset(bad, GateContext.make()).violations} == {"banned_word"}


class GateContext:
    @staticmethod
    def make():
        from adlantis.rules import RuleContext

        return RuleContext(brand=INPUTS.brand, facts=INPUTS.facts, today=TODAY)


def test_broad_sections_cite_only_unexpired_facts() -> None:
    from tests.orchestrator.kit_helpers import STRATEGY

    sections = strategy_sections(STRATEGY, INPUTS.facts, TODAY)
    assert "F-010" not in sections[0].references and "F-001" in sections[0].references


def test_image_section_leaves_out_the_standing_restrictions() -> None:
    prompt = ImagePrompt(
        asset_id="email-1",
        channel="email",
        prompt=with_safety_suffix("A mug."),
        alt_text="A cup.",
        size="1024x1024",
    )
    section = image_sections(DesignResult(prompts=[prompt]), INPUTS.facts, TODAY)[0]
    assert section.fields == {"prompt": "A mug.", "alt_text": "A cup."}


def test_section_gate_accepts_a_proof_from_its_sources() -> None:
    from tests.orchestrator.kit_helpers import STRATEGY

    section = strategy_sections(STRATEGY, INPUTS.facts, TODAY)[0]
    text = "Hollow Reserve tastes of red apple, panela, and cocoa."
    proven = section.model_copy(update={"fields": {"positioning": text}})
    draft = DraftClaim(
        field="positioning",
        quote=text,
        claim_type="product_fact",
        references=["F-003"],
        verdict="supported",
        supporting_passage=text,
        reason="F-003 says so.",
    )
    ctx = GateContext.make()
    result = settle_claims([draft], proven, ctx, EvidenceStore(), check_asset(proven, ctx))
    assert result.passed


def test_section_edits_keep_their_sources_and_add_new_ones() -> None:
    from tests.orchestrator.kit_helpers import STRATEGY

    section = strategy_sections(STRATEGY, INPUTS.facts, TODAY)[2]
    edit = AssetEdit(
        issue_id="I1",
        field="message",
        find="Every bag",
        replace="Each bag",
        references=["F-003"],
    )
    allowed = frozenset({"F-001", "F-003"})
    revised = apply_edits(section, RevisionPlan(edits=[edit]), {"I1"}, allowed).asset
    assert revised.references == ["F-001", "F-003"]


def test_glossary_source_shows_its_term_once() -> None:
    wording = INPUTS.brand.glossary[0].wording
    kit = make_kit(reviewed(references=[], quote=wording, supporting_passage=wording))
    page = render_html(kit)
    assert f"glossary: {wording}" in page
    assert f"{INPUTS.brand.glossary[0].term}: {wording}" not in page


def test_kit_json_records_the_verified_sections(tmp_path) -> None:
    write_kit(make_kit(), tmp_path)
    data = json.loads((tmp_path / "kit.json").read_text())
    assert [s["asset"]["channel"] for s in data["verified_sections"]] == ["strategy"] * 4


def _kit_with_section(section: ReviewedAsset):
    kit = make_kit()
    others = [s for s in kit.verified_sections if s.asset.asset_id != section.asset.asset_id]
    return kit.model_copy(update={"verified_sections": [section, *others]})


@pytest.mark.parametrize("verdict", ["unsupported", "prohibited"])
def test_recorded_section_with_a_failed_claim_counts_as_unverified(verdict: str) -> None:
    section = make_kit().verified_sections[0]
    failed = section.model_copy(
        update={"claims": [make_claim(section.asset.asset_id, verdict=verdict)]}
    )
    assert unverified_statements(_kit_with_section(failed)) == ["positioning"]


def test_recorded_section_with_a_blocking_rule_counts_as_unverified() -> None:
    section = make_kit().verified_sections[0]
    violation = RuleViolation(
        rule="banned_word", asset_id=section.asset.asset_id, message="Banned.", fix="Remove."
    )
    failed = section.model_copy(update={"warnings": [violation]})
    assert unverified_statements(_kit_with_section(failed)) == ["positioning"]


def test_recorded_section_with_only_a_warning_still_counts_as_verified() -> None:
    section = make_kit().verified_sections[0]
    violation = RuleViolation(
        rule="channel_limit",
        severity="warning",
        asset_id=section.asset.asset_id,
        message="Long.",
        fix="Trim.",
    )
    warned = section.model_copy(update={"warnings": [violation]})
    assert unverified_statements(_kit_with_section(warned)) == []
