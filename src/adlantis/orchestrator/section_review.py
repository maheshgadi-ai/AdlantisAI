"""Verifies the parts of a kit that are not published copy: the strategy and image prompts."""

from __future__ import annotations

from datetime import date

from adlantis.rules.image_prompts import SAFETY_SUFFIX
from adlantis.rules.text import REFERENCE_ID
from adlantis.schemas.channels import CHANNEL_PLAN_PREFIX, KitSection
from adlantis.schemas.copy import CampaignAsset
from adlantis.schemas.design import DesignResult, ImagePrompt, RejectedImagePrompt
from adlantis.schemas.facts import FactSheet
from adlantis.schemas.kit import CampaignKit
from adlantis.schemas.ledger import IssueLedger
from adlantis.schemas.review import AssetGap, ReviewedAsset, ReviewOutcome
from adlantis.schemas.strategy import CampaignStrategy, ChannelPlan, KeyMessage


class SectionFailure(RuntimeError):
    """A required section could not be verified, so the campaign cannot ship."""


def _section(
    asset_id: str,
    channel: KitSection,
    fields: dict[str, str],
    references: list[str],
    usable: frozenset[str],
) -> CampaignAsset:
    """A reviewable section that carries every usable source its text names."""
    named = {ref for text in fields.values() for ref in REFERENCE_ID.findall(text)} & usable
    return CampaignAsset(
        asset_id=asset_id, channel=channel, fields=fields, references=sorted({*references, *named})
    )


def _active_facts(facts: FactSheet, today: date) -> list[str]:
    return [fact.id for fact in facts.facts if not fact.is_expired(today)]


def strategy_sections(
    strategy: CampaignStrategy,
    facts: FactSheet,
    today: date,
    evidence_ids: frozenset[str] = frozenset(),
) -> list[CampaignAsset]:
    """One reviewable section per statement in the strategy."""
    active = _active_facts(facts, today)
    usable = frozenset(active) | evidence_ids
    sections = [
        _section(
            "strategy-positioning",
            "strategy",
            {"positioning": strategy.positioning},
            active,
            usable,
        ),
        _section("strategy-concept", "strategy", {"concept": strategy.concept}, active, usable),
    ]
    sections += [
        _section(
            f"strategy-message-{number}",
            "strategy",
            {"message": message.message},
            message.references,
            usable,
        )
        for number, message in enumerate(strategy.key_messages, 1)
    ]
    sections += [
        _section(
            f"{CHANNEL_PLAN_PREFIX}{plan.channel}",
            "strategy",
            {"role": plan.role, "rationale": plan.rationale},
            active,
            usable,
        )
        for plan in strategy.channel_mix
    ]
    return sections


def _reason(gap: AssetGap, ledger: IssueLedger) -> str:
    issues = (ledger.get(issue_id) for issue_id in gap.issue_ids)
    problems = [issue.problem for issue in issues if issue is not None]
    return "; ".join(problems) or gap.reason


def _explained(gaps: list[AssetGap], ledger: IssueLedger) -> list[AssetGap]:
    return [gap.model_copy(update={"reason": _reason(gap, ledger)}) for gap in gaps]


def rebuild_strategy(
    original: CampaignStrategy, outcome: ReviewOutcome
) -> tuple[CampaignStrategy, list[AssetGap]]:
    """The strategy made only of statements that passed, and a gap for each one removed.

    Raises:
        SectionFailure: If the positioning, the concept, or every key message failed.
    """
    passed = {item.asset.asset_id: item.asset for item in outcome.assets}
    gaps = _explained(outcome.gaps, outcome.ledger)
    for required in ("strategy-positioning", "strategy-concept"):
        if required not in passed:
            reason = next((g.reason for g in gaps if g.asset_id == required), "It was not checked.")
            raise SectionFailure(f"{required} could not be verified: {reason}")
    messages = [
        KeyMessage(
            message=passed[f"strategy-message-{number}"].fields["message"],
            references=passed[f"strategy-message-{number}"].references or message.references,
        )
        for number, message in enumerate(original.key_messages, 1)
        if f"strategy-message-{number}" in passed
    ]
    if not messages:
        raise SectionFailure("No key message could be verified.")
    channels = [
        ChannelPlan(
            channel=plan.channel,
            role=passed[f"strategy-channel-{plan.channel}"].fields["role"],
            rationale=passed[f"strategy-channel-{plan.channel}"].fields["rationale"],
        )
        for plan in original.channel_mix
        if f"strategy-channel-{plan.channel}" in passed
    ]
    if not channels:
        raise SectionFailure("No channel plan could be verified.")
    strategy = CampaignStrategy(
        positioning=passed["strategy-positioning"].fields["positioning"],
        concept=passed["strategy-concept"].fields["concept"],
        key_messages=messages,
        channel_mix=channels,
    )
    return strategy, gaps


def _prompt_fields(prompt: ImagePrompt) -> dict[str, str]:
    body = prompt.prompt.removesuffix(SAFETY_SUFFIX).strip()
    return {"prompt": body, "alt_text": prompt.alt_text}


def image_sections(
    design: DesignResult,
    facts: FactSheet,
    today: date,
    evidence_ids: frozenset[str] = frozenset(),
) -> list[CampaignAsset]:
    """One reviewable section per image prompt, without the standing restrictions."""
    active = _active_facts(facts, today)
    usable = frozenset(active) | evidence_ids
    return [
        _section(f"image-{p.asset_id}", "image_prompt", _prompt_fields(p), active, usable)
        for p in design.prompts
    ]


def apply_image_review(design: DesignResult, outcome: ReviewOutcome) -> DesignResult:
    """Keep the prompts that passed. Each failure is listed with its reason."""
    passed = {item.asset.asset_id for item in outcome.assets}
    reasons = {g.asset_id: g.reason for g in _explained(outcome.gaps, outcome.ledger)}
    kept = [p for p in design.prompts if f"image-{p.asset_id}" in passed]
    failed = [
        RejectedImagePrompt(asset_id=p.asset_id, reason=reasons.get(f"image-{p.asset_id}", ""))
        for p in design.prompts
        if f"image-{p.asset_id}" not in passed
    ]
    return DesignResult(prompts=kept, rejected=[*design.rejected, *failed])


def _passes(section: ReviewedAsset) -> bool:
    return all(claim.verdict == "supported" for claim in section.claims) and all(
        violation.severity != "error" for violation in section.warnings
    )


def _expected(kit: CampaignKit) -> list[tuple[str, dict[str, str]]]:
    expected: list[tuple[str, dict[str, str]]] = []
    if kit.strategy is not None:
        strategy = kit.strategy
        expected += [
            ("positioning", {"positioning": strategy.positioning}),
            ("concept", {"concept": strategy.concept}),
        ]
        expected += [("key message", {"message": m.message}) for m in strategy.key_messages]
        expected += [
            (f"{p.channel} plan", {"role": p.role, "rationale": p.rationale})
            for p in strategy.channel_mix
        ]
    expected += [(f"{p.asset_id} image prompt", _prompt_fields(p)) for p in kit.image_prompts]
    return expected


def unverified_statements(kit: CampaignKit) -> list[str]:
    """Every strategy statement or image prompt in the kit without a passing verification."""
    verified = [s.asset.fields for s in kit.verified_sections if _passes(s)]
    return [label for label, fields in _expected(kit) if fields not in verified]
