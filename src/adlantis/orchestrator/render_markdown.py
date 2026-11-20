"""Renders a campaign kit as Markdown."""

from __future__ import annotations

from adlantis.orchestrator.render_common import CHANNEL_TITLES, safe_url, status_line
from adlantis.schemas.kit import AppendixClaim, CampaignKit, ClaimSource


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _quoted(text: str) -> list[str]:
    return [f"> {line}".rstrip() for line in text.splitlines()] or [">"]


def _source(source: ClaimSource) -> str:
    if source.kind == "evidence":
        url = safe_url(source.url)
        label = _cell(source.title or source.reference)
        return f"{source.reference}: [{label}](<{url}>)" if url else f"{source.reference}: {label}"
    return f"{source.kind} {_cell(source.reference)}"


def _strategy(kit: CampaignKit) -> list[str]:
    if kit.strategy is None:
        return ["## Summary", "", kit.summary, ""] if kit.summary else []
    lines = [
        "## Strategy",
        "",
        f"**Positioning:** {kit.strategy.positioning}",
        "",
        f"**Concept:** {kit.strategy.concept}",
        "",
        "**Key messages:**",
        "",
    ]
    lines += [f"- {m.message} ({', '.join(m.references)})" for m in kit.strategy.key_messages]
    lines += ["", f"**Channel plans.** {kit.channel_plan_label}", ""]
    lines += [
        f"- {CHANNEL_TITLES[p.channel]}: {p.role} {p.rationale}" for p in kit.strategy.channel_mix
    ]
    return [*lines, ""]


def _assets(kit: CampaignKit) -> list[str]:
    lines = ["## Assets", ""]
    prompts = {prompt.asset_id: prompt for prompt in kit.image_prompts}
    images = {image.asset_id: image for image in kit.images}
    for item in kit.assets:
        asset = item.asset
        lines += [f"### {asset.asset_id} ({CHANNEL_TITLES[asset.channel]})", ""]
        for name, text in asset.fields.items():
            lines += [f"**{name}**", "", *_quoted(text), ""]
        lines += [f"- Warning: {warning.message}" for warning in item.warnings]
        prompt = prompts.get(asset.asset_id)
        if prompt:
            lines.append(f"- Image prompt: {prompt.prompt}")
        image = images.get(asset.asset_id)
        if image:
            lines.append(f"- {image.label}: ![{_cell(image.alt_text)}]({image.file})")
        lines.append("")
    return lines


def _claim_row(claim: AppendixClaim) -> str:
    sources = "; ".join(_source(source) for source in claim.sources) or "None"
    return (
        f"| {claim.id} | {_cell(claim.quote)} | {claim.claim_type} | {claim.verdict} | {sources} |"
    )


def _appendix(kit: CampaignKit) -> list[str]:
    lines = ["## Claims appendix", ""]
    if not kit.verified:
        return [*lines, "Claims in this kit were not verified.", ""]
    if not kit.claims:
        return [*lines, "This kit makes no factual claims.", ""]
    lines += ["| Claim | Text | Type | Verdict | Evidence |", "| --- | --- | --- | --- | --- |"]
    return [*lines, *(_claim_row(claim) for claim in kit.claims), ""]


def _ledger(kit: CampaignKit) -> list[str]:
    if not kit.ledger.issues:
        return []
    header = "| Issue | Asset | Status | Problem |"
    lines = ["## Issue ledger", "", header, "| --- | --- | --- | --- |"]
    lines += [
        f"| {issue.id} | {issue.asset_id} | {issue.status} | {_cell(issue.problem)} |"
        for issue in kit.ledger.issues
    ]
    return [*lines, ""]


def render_markdown(kit: CampaignKit) -> str:
    """The whole kit as one Markdown document."""
    lines = [f"# {kit.brand_name}: {kit.product_name}", "", f"**{status_line(kit)}**", ""]
    lines += _strategy(kit) + _assets(kit)
    if kit.gaps:
        lines += ["## Gaps", ""]
        lines += [f"- {gap.asset_id}: {gap.reason}" for gap in kit.gaps]
        lines.append("")
    lines += _appendix(kit) + _ledger(kit)
    if kit.research_gaps:
        lines += ["## Research gaps", "", *(f"- {gap}" for gap in kit.research_gaps), ""]
    lines += ["## Cost", "", f"${kit.cost.total_usd:.4f} of a ${kit.cost.cap_usd:.2f} cap", ""]
    return "\n".join(lines)
