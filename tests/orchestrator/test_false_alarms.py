"""Regression tests built from the text of false alarms seen in a live campaign run."""

import asyncio
import json

import pytest

from adlantis.agents import ClaimChecker
from adlantis.orchestrator.pipeline import CampaignPipeline, PipelineOptions
from adlantis.orchestrator.revision import apply_edits
from adlantis.orchestrator.run_log import RunLog
from adlantis.orchestrator.section_review import strategy_sections
from adlantis.rules import RuleContext, check_asset
from adlantis.rules.claim_gate import settle_claims
from adlantis.rules.image_prompts import with_safety_suffix
from adlantis.schemas import (
    AssetEdit,
    CampaignAsset,
    CampaignStrategy,
    ChannelPlan,
    Citation,
    ClaimCheckDraft,
    DraftClaim,
    EvidenceStore,
    ResearchResult,
    RevisionPlan,
    SourceRating,
    StrategyResult,
)
from tests.agents.copy_helpers import router
from tests.fakes import anthropic_response
from tests.orchestrator.kit_helpers import (
    INPUTS,
    STRATEGY,
    TODAY,
    StubChecker,
    StubDesigner,
    stub_team,
    web_evidence,
)

CTX = RuleContext(brand=INPUTS.brand, facts=INPUTS.facts, today=TODAY)
ALLOWED = frozenset({"F-004", "F-009", "F-011", "E-6", "E-21"})
FACT = "We have bought from Finca Monte Tamsal for 7 consecutive harvests."
QUOTED_FACT = f'"{FACT}" - F-004'
MARKET = "35% of past-day specialty coffee drinkers say flavor helps define specialty coffee."
RESEARCH_LINE = (
    "Market research shows that flavor and single-origin detail matter to specialty buyers "
    "(E-21, E-6)."
)


def store() -> EvidenceStore:
    """Evidence with the real IDs from the run: E-6 and E-21 hold distinct text."""
    evidence = EvidenceStore()
    rating = SourceRating(score=0.9, tier="high", label="news", rule="domain:publisher.example")
    for number in range(1, 22):
        excerpt = {21: MARKET, 6: "Buyers respond to detail on roast and origin."}.get(
            number, f"Unrelated source {number}."
        )
        evidence.add(
            url=f"https://publisher.example/{number}",
            title=f"Report {number}",
            excerpt=excerpt,
            tool="web_search",
            rating=rating,
        )
    return evidence


def section(text: str, *references: str, field: str = "rationale") -> CampaignAsset:
    return CampaignAsset(
        asset_id="strategy-channel-email",
        channel="strategy",
        fields={field: text},
        references=list(references),
    )


def published(text: str, *references: str) -> CampaignAsset:
    return CampaignAsset(
        asset_id="email-1", channel="email", fields={"body": text}, references=list(references)
    )


def quote_violations(asset: CampaignAsset) -> list:
    return check_asset(asset, CTX).for_rule("testimonial_claim")


def draft(quote: str, reference: str, passage: str) -> DraftClaim:
    return DraftClaim(
        field="rationale",
        quote=quote,
        claim_type="statistic",
        references=[reference],
        verdict="supported",
        supporting_passage=passage,
        reason="The source says so.",
    )


def settled(asset: CampaignAsset, *drafts: DraftClaim):
    evidence = store()
    return settle_claims(list(drafts), asset, CTX, evidence, check_asset(asset, CTX))


# The false gap: a revision on a plan section must not create a statement needing its own verdict.


def test_revision_that_adds_a_source_does_not_create_a_false_gap() -> None:
    text = "The launch email leads with the harvest."
    edit = AssetEdit(
        issue_id="I1",
        field="rationale",
        find="leads with the harvest",
        replace="says the harvest year (F-011) is the news",
        references=["F-011"],
    )
    revised = apply_edits(section(text, "F-004"), RevisionPlan(edits=[edit]), {"I1"}, ALLOWED).asset
    assert revised.citations == []
    assert revised.references == ["F-004", "F-011"]
    assert settled(revised).passed


def test_revision_of_published_copy_still_cites_its_new_statement() -> None:
    asset = published("Fresh.", "F-004")
    edit = AssetEdit(issue_id="I1", field="body", find="Fresh.", replace=FACT, references=["F-004"])
    revised = apply_edits(asset, RevisionPlan(edits=[edit]), {"I1"}, ALLOWED).asset
    assert revised.citations == [Citation(text=FACT, references=["F-004"])]


def test_source_named_in_revised_plan_text_is_attached() -> None:
    edit = AssetEdit(issue_id="I1", field="rationale", find="Flavor", replace="Flavor (E-21)")
    revised = apply_edits(section("Flavor"), RevisionPlan(edits=[edit]), {"I1"}, ALLOWED).asset
    assert revised.references == ["E-21"]


def test_unusable_source_named_in_revised_plan_text_is_not_attached() -> None:
    edit = AssetEdit(issue_id="I1", field="rationale", find="Flavor", replace="Flavor (E-99)")
    revised = apply_edits(section("Flavor"), RevisionPlan(edits=[edit]), {"I1"}, ALLOWED).asset
    assert revised.references == []


# Citation IDs are not numbers in the claim.


ROAST = "Roasted within 48 hours of shipping"


@pytest.mark.parametrize(
    ("quote", "reference", "passage"),
    [
        (f"{ROAST} (F-001).", "F-001", "Roasted within 48 hours of shipping."),
        (f"{MARKET[:-1]} (E-21).", "E-21", MARKET),
    ],
)
def test_citation_ids_are_not_read_as_numbers(quote: str, reference: str, passage: str) -> None:
    result = settled(section(quote, reference), draft(quote, reference, passage))
    assert result.claims[0].verdict == "supported"


def test_reworded_exact_fact_is_refused_for_its_wording_and_not_for_its_id() -> None:
    quote = "the 7-harvest relationship (F-004)"
    claim = settled(section(quote, "F-004"), draft(quote, "F-004", FACT)).claims[0]
    assert claim.reason == "The approved fact must be used in its exact wording."


def test_wrong_number_beside_a_citation_is_still_caught() -> None:
    quote = "the 9-harvest relationship (F-004)"
    claim = settled(section(quote, "F-004"), draft(quote, "F-004", FACT)).claims[0]
    assert claim.reason == "The claim states a number the cited source does not contain."


def test_an_id_that_is_not_a_source_still_counts_as_a_number() -> None:
    quote = f"{ROAST}, built like the F-150 (F-001)"
    passage = "Roasted within 48 hours of shipping."
    claim = settled(section(quote, "F-001"), draft(quote, "F-001", passage)).claims[0]
    assert claim.reason == "The claim states a number the cited source does not contain."


# Quotation marks alone do not make a testimonial.


def test_quoted_approved_fact_with_its_id_is_not_a_testimonial() -> None:
    assert quote_violations(section(QUOTED_FACT, "F-004")) == []


def test_quoted_approved_fact_in_published_copy_is_not_a_testimonial() -> None:
    assert quote_violations(published(QUOTED_FACT, "F-004")) == []


def test_quoted_fact_without_any_attribution_is_not_a_testimonial() -> None:
    assert quote_violations(published(f'"{FACT}"')) == []


def test_plan_may_refer_to_the_approved_testimonial() -> None:
    text = "The testimonial (F-009) comes from a subscriber"
    assert quote_violations(section(text, "F-009")) == []


def test_published_copy_may_not_promise_testimonials() -> None:
    assert quote_violations(published("Read our testimonials.")) != []


def test_plan_may_not_state_an_invented_endorsement() -> None:
    assert quote_violations(section("Customers love it, and testimonials prove it.")) != []


@pytest.mark.parametrize(
    "text",
    [
        f'"{FACT}" - Dana Reyes',
        '"We have bought from them for 9 harvests." - F-004',
        '"Best coffee I ever had." - F-004',
    ],
)
def test_invented_or_person_attributed_quotes_are_still_testimonials(text: str) -> None:
    assert quote_violations(published(text, "F-004")) != []


def test_quote_of_a_fact_the_asset_does_not_cite_is_still_caught() -> None:
    assert quote_violations(published(QUOTED_FACT)) != []


def test_quote_of_an_expired_fact_is_still_caught() -> None:
    wording = INPUTS.facts.get("F-010").claim
    assert quote_violations(published(f'"{wording}" - F-010', "F-010")) != []


def test_quote_of_an_unknown_fact_is_still_caught() -> None:
    assert quote_violations(published(f'"{FACT}" - F-999', "F-999")) != []


# Every cited source reaches the checker.


def plan(rationale: str = RESEARCH_LINE, references: tuple[str, ...] = ("F-003",)):
    return CampaignStrategy(
        positioning="Traceable coffee (F-002).",
        concept="Know the farm.",
        key_messages=[{"message": "Tastes of cocoa (E-21).", "references": list(references)}],
        channel_mix=[{"channel": "search_ad", "role": "Capture", "rationale": rationale}],
    )


def sections(strategy=None, usable: frozenset[str] = frozenset({"E-6", "E-21"})) -> dict:
    built = strategy_sections(strategy or plan(), INPUTS.facts, TODAY, usable)
    return {item.asset_id: item for item in built}


def test_evidence_named_in_a_channel_plan_is_attached() -> None:
    assert {"E-6", "E-21"} <= set(sections()["strategy-channel-search_ad"].references)


def test_evidence_named_in_a_key_message_is_attached() -> None:
    assert sections()["strategy-message-1"].references == ["E-21", "F-003"]


def test_fact_named_in_the_positioning_is_attached() -> None:
    assert "F-002" in sections()["strategy-positioning"].references


def test_quarantined_evidence_is_not_attached() -> None:
    assert (
        "E-21" not in sections(usable=frozenset({"E-6"}))["strategy-channel-search_ad"].references
    )


def test_expired_fact_is_not_attached() -> None:
    text = "The old sampler (F-010) is gone."
    assert "F-010" not in sections(plan(text))["strategy-channel-search_ad"].references


def test_checker_receives_the_text_of_every_cited_source() -> None:
    built, calls = router(anthropic_response(ClaimCheckDraft().model_dump_json()))
    asset = sections()["strategy-channel-search_ad"]
    ClaimChecker(built, CTX, store()).run(asset)
    sent = json.dumps(calls["anthropic"][0]["messages"])
    assert MARKET in sent and "Buyers respond to detail on roast and origin." in sent


class _Research:
    def run(self, _brief) -> ResearchResult:
        return ResearchResult(evidence=web_evidence())


class _Strategist:
    def run(self, _request) -> StrategyResult:
        plans = [{"channel": "email", "role": "Launch", "rationale": "Flavor matters (E-1)."}]
        return StrategyResult(
            strategy=STRATEGY.model_copy(
                update={"channel_mix": [ChannelPlan.model_validate(item) for item in plans]}
            )
        )


class _Recording(StubChecker):
    def __init__(self) -> None:
        super().__init__()
        self.seen: dict[str, list[str]] = {}

    def run(self, asset):
        self.seen[asset.asset_id] = asset.references
        return super().run(asset)


def test_pipeline_attaches_evidence_named_in_plans_and_image_prompts() -> None:
    checker = _Recording()
    team = stub_team(
        researcher=_Research(),
        strategist=_Strategist(),
        designer=StubDesigner(prompt=with_safety_suffix("A quiet table (E-1).")),
        checker=checker,
    )
    asyncio.run(CampaignPipeline(INPUTS, team, RunLog(), PipelineOptions(today=TODAY)).run())
    assert "E-1" in checker.seen["strategy-channel-email"]
    assert "E-1" in checker.seen["image-email-1"]
