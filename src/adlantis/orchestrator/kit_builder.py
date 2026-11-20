"""Assembles the campaign kit and its claims appendix. This step is code, not a model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from adlantis.orchestrator.section_review import unverified_statements
from adlantis.schemas.claim_check import CheckedClaim
from adlantis.schemas.design import DesignResult, GeneratedImage
from adlantis.schemas.evidence_store import EvidenceStore
from adlantis.schemas.inputs import CampaignInputs
from adlantis.schemas.kit import AppendixClaim, CampaignKit, ClaimSource, KitCost
from adlantis.schemas.review import AssetGap, ReviewedAsset, ReviewOutcome
from adlantis.schemas.strategy import CampaignStrategy


class KitBlocked(RuntimeError):
    """A section of the kit failed verification, so the kit cannot be built."""


@dataclass(frozen=True)
class KitParts:
    """What a finished run hands to the packager."""

    run_id: str
    created_at: datetime
    profile: str
    inputs: CampaignInputs
    strategy: CampaignStrategy
    review: ReviewOutcome
    evidence: EvidenceStore
    cost: KitCost
    research_gaps: list[str] = field(default_factory=list)
    design: DesignResult = field(default_factory=DesignResult)
    images: list[GeneratedImage] = field(default_factory=list)
    extra_gaps: list[AssetGap] = field(default_factory=list)
    sections: list[ReviewedAsset] = field(default_factory=list)


def claim_sources(
    claim: CheckedClaim, inputs: CampaignInputs, evidence: EvidenceStore
) -> list[ClaimSource]:
    """Everything that backs one claim."""
    sources: list[ClaimSource] = []
    for reference in claim.references:
        fact = inputs.facts.get(reference)
        record = evidence.get(reference)
        if fact is not None:
            sources.append(
                ClaimSource(
                    reference=reference,
                    kind="fact",
                    text=fact.claim,
                    note=fact.evidence_note,
                    expires=fact.expires,
                )
            )
        elif record is not None and record.status == "usable":
            sources.append(
                ClaimSource(
                    reference=reference,
                    kind="evidence",
                    text=claim.supporting_passage,
                    url=record.url,
                    title=record.title,
                )
            )
    for entry in inputs.brand.glossary:
        if claim.supporting_passage == entry.wording:
            sources.append(ClaimSource(reference=entry.term, kind="glossary", text=entry.wording))
    return sources


def _unshippable(
    item: ReviewedAsset, inputs: CampaignInputs, evidence: EvidenceStore
) -> str | None:
    """Why an asset may not enter the kit, checked again here as a last line of defense."""
    if any(claim.verdict != "supported" for claim in item.claims):
        return "A claim in this asset is not supported."
    if any(violation.severity == "error" for violation in item.warnings):
        return "A blocking rule violation remains in this asset."
    if any(not claim_sources(claim, inputs, evidence) for claim in item.claims):
        return "A claim in this asset has no traceable source."
    return None


def _appendix(item: ReviewedAsset, parts: KitParts) -> list[AppendixClaim]:
    return [
        AppendixClaim(
            id=claim.id,
            asset_id=claim.asset_id,
            channel=item.asset.channel,
            field=claim.field,
            quote=claim.quote,
            claim_type=claim.claim_type,
            verdict=claim.verdict,
            decided_by=claim.decided_by,
            rule=claim.rule,
            reason=claim.reason,
            sources=claim_sources(claim, parts.inputs, parts.evidence),
        )
        for claim in item.claims
    ]


def seal(kit: CampaignKit) -> CampaignKit:
    """Record the fingerprint that a sign-off will later be checked against."""
    return kit.model_copy(update={"content_sha256": kit.compute_hash()})


def build_team_kit(parts: KitParts) -> CampaignKit:
    """Package a verified campaign. Only assets that pass every check are included."""
    shipped: list[ReviewedAsset] = []
    gaps = [*parts.review.gaps, *parts.extra_gaps]
    for item in parts.review.assets:
        reason = _unshippable(item, parts.inputs, parts.evidence)
        if reason:
            gaps.append(
                AssetGap(asset_id=item.asset.asset_id, channel=item.asset.channel, reason=reason)
            )
        else:
            shipped.append(item)
    kept = {item.asset.asset_id for item in shipped}
    sections = [s for s in parts.sections if not _unshippable(s, parts.inputs, parts.evidence)]
    kit = seal(
        CampaignKit(
            run_id=parts.run_id,
            created_at=parts.created_at,
            profile=parts.profile,
            brand_name=parts.inputs.brand.name,
            brand_colors=parts.inputs.brand.colors,
            product_name=parts.inputs.product.name,
            strategy=parts.strategy,
            assets=shipped,
            verified_sections=sections,
            gaps=gaps,
            claims=[claim for item in [*shipped, *sections] for claim in _appendix(item, parts)],
            ledger=parts.review.ledger,
            research_gaps=parts.research_gaps,
            image_prompts=[p for p in parts.design.prompts if p.asset_id in kept],
            rejected_image_prompts=[r for r in parts.design.rejected if r.asset_id in kept],
            images=[image for image in parts.images if image.asset_id in kept],
            cost=parts.cost,
        )
    )
    unverified = unverified_statements(kit)
    if unverified:
        raise KitBlocked(f"These kit sections did not pass verification: {', '.join(unverified)}")
    return kit


def build_baseline_kit(
    *,
    run_id: str,
    created_at: datetime,
    profile: str,
    inputs: CampaignInputs,
    summary: str,
    assets: list[ReviewedAsset],
    cost: KitCost,
    gaps: list[AssetGap] | None = None,
) -> CampaignKit:
    """Package a baseline for evaluation. Its claims are unverified, so it can never be approved."""
    return seal(
        CampaignKit(
            run_id=run_id,
            mode="baseline",
            verified=False,
            created_at=created_at,
            profile=profile,
            brand_name=inputs.brand.name,
            brand_colors=inputs.brand.colors,
            product_name=inputs.product.name,
            summary=summary,
            assets=assets,
            gaps=gaps or [],
            cost=cost,
        )
    )
