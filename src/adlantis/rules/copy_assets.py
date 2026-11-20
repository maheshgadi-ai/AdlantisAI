"""Turns a model's draft variants into checked campaign assets."""

from __future__ import annotations

from datetime import date

from adlantis.rules.channels import load_channel_limits
from adlantis.rules.text import contains_text
from adlantis.schemas.channels import Channel
from adlantis.schemas.copy import (
    ASSET_VARIANTS,
    CampaignAsset,
    ChannelCopy,
    ChannelDraft,
    Citation,
    DraftVariant,
)
from adlantis.schemas.facts import FactSheet
from adlantis.schemas.research import ResearchFinding
from adlantis.schemas.review import AssetGap


def allowed_references(
    facts: FactSheet, findings: list[ResearchFinding], today: date
) -> frozenset[str]:
    """The sources copy may cite: unexpired facts and evidence behind accepted findings."""
    active = {fact.id for fact in facts.facts if not fact.is_expired(today)}
    return frozenset(active | {e for finding in findings for e in finding.evidence_ids})


def build_channel_copy(
    draft: ChannelDraft, channel: Channel, allowed: frozenset[str], mentions: dict[str, str]
) -> ChannelCopy:
    """Keep the usable variants for one channel and say why the others were refused."""
    required = set(load_channel_limits().channels[channel])
    assets: list[CampaignAsset] = []
    rejected: list[str] = []
    for number, variant in enumerate(draft.variants[: ASSET_VARIANTS[channel]], 1):
        problem = _variant_problem(variant, required, mentions)
        if problem:
            rejected.append(f"Variant {number}: {problem}")
            continue
        fields = {field.name: field.text for field in variant.fields}
        citations = _usable_citations(variant.citations, fields, allowed)
        assets.append(
            CampaignAsset(
                asset_id=f"{channel}-{len(assets) + 1}",
                channel=channel,
                fields=fields,
                citations=citations,
                references=sorted({r for citation in citations for r in citation.references}),
            )
        )
    returned = len(draft.variants)
    rejected += [
        f"Variant {number}: was not returned by the model"
        for number in range(returned + 1, ASSET_VARIANTS[channel] + 1)
    ]
    return ChannelCopy(assets=assets, rejected=rejected)


def variant_gaps(channel: Channel, rejected: list[str]) -> list[AssetGap]:
    """One gap for each variant that could not be used, with the reason."""
    gaps: list[AssetGap] = []
    for entry in rejected:
        label, _, reason = entry.partition(": ")
        number = label.removeprefix("Variant ").strip()
        asset_id = f"{channel}-variant-{number}"
        gaps.append(AssetGap(asset_id=asset_id, channel=channel, reason=reason))
    return gaps


def _variant_problem(
    variant: DraftVariant, required: set[str], mentions: dict[str, str]
) -> str | None:
    names = [field.name for field in variant.fields]
    if len(names) != len(set(names)) or set(names) != required:
        return f"needs exactly these fields: {sorted(required)}"
    if any(not field.text.strip() for field in variant.fields):
        return "has an empty field"
    texts = {field.name: field.text for field in variant.fields}
    missing = [field for field, name in mentions.items() if not contains_text(texts[field], name)]
    if missing:
        return f"must name the product in: {sorted(missing)}"
    return None


def _usable_citations(
    citations: list[Citation], fields: dict[str, str], allowed: frozenset[str]
) -> list[Citation]:
    """Drop citations of unusable sources, which leaves the statement uncited for the checker."""
    usable: list[Citation] = []
    for citation in citations:
        references = [r for r in citation.references if r in allowed]
        if references and any(contains_text(text, citation.text) for text in fields.values()):
            usable.append(Citation(text=citation.text, references=references))
    return usable
