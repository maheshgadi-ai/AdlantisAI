"""Renders a campaign kit as one styled, standalone HTML page."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from html import escape

from adlantis.orchestrator.render_common import CHANNEL_TITLES, safe_url, status_line
from adlantis.schemas.kit import AppendixClaim, CampaignKit, ClaimSource

_POLICY = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
_STYLE = """
:root{--accent:__ACCENT__;--ink:#1f2421;--muted:#5d655f;--line:#d9ddd8;--page:#fbfaf7;
--card:#fff;--warn:#8a5a00;--warn-bg:#fff4dc;--ok:#23663a;--ok-bg:#e5f4e9}
@media (prefers-color-scheme:dark){:root{--ink:#eceee9;--muted:#a9b0a9;--line:#3a403b;
--page:#171a18;--card:#202421;--warn:#f2c76b;--warn-bg:#3a2f15;--ok:#8bd6a2;--ok-bg:#1d3325}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:32px 16px 64px}
h1{margin:0 0 12px;font-size:2rem;line-height:1.2}
h2{margin:40px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--accent)}
h3{margin:0 0 10px;font-size:1.05rem}
.status{padding:10px 14px;border-radius:6px;background:var(--warn-bg);color:var(--warn);
font-weight:600}
.status.approved{background:var(--ok-bg);color:var(--ok)}
.card{margin:14px 0;padding:16px;background:var(--card);border:1px solid var(--line);
border-radius:8px}
.label{margin:10px 0 2px;color:var(--muted);font-size:.8rem;font-weight:600;
text-transform:uppercase}
.copy{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}
.note{color:var(--muted);font-size:.9rem}
img{display:block;max-width:100%;height:auto;margin-top:10px;border-radius:6px}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th,td{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
a{color:inherit}
"""


def _e(text: object) -> str:
    return escape(str(text), quote=True)


def _source(source: ClaimSource) -> str:
    if source.kind == "glossary":
        return f"glossary: {_e(source.text)}"
    url = safe_url(source.url)
    if source.kind == "evidence" and url:
        label = _e(source.title or source.reference)
        link = f'<a href="{_e(url)}" rel="noopener noreferrer">{label}</a>'
        return f"{_e(source.reference)}: {link}"
    return f"{_e(source.kind)} {_e(source.reference)}: {_e(source.text)}"


def _claim_row(claim: AppendixClaim) -> str:
    sources = "<br>".join(_source(source) for source in claim.sources) or "None"
    cells = (_e(claim.id), _e(claim.quote), _e(claim.claim_type), _e(claim.verdict), sources)
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def _table(headers: tuple[str, ...], rows: list[str]) -> str:
    head = "".join(f"<th>{_e(header)}</th>" for header in headers)
    return f'<div class="scroll"><table><tr>{head}</tr>{"".join(rows)}</table></div>'


def _strategy(kit: CampaignKit) -> str:
    if kit.strategy is None:
        return f"<h2>Summary</h2><p>{_e(kit.summary)}</p>" if kit.summary else ""
    messages = "".join(
        f"<li>{_e(m.message)} <span class=note>({_e(', '.join(m.references))})</span></li>"
        for m in kit.strategy.key_messages
    )
    plans = "".join(
        f"<li><strong>{_e(CHANNEL_TITLES[p.channel])}:</strong> {_e(p.role)} {_e(p.rationale)}</li>"
        for p in kit.strategy.channel_mix
    )
    return (
        f"<h2>Strategy</h2><p><strong>Positioning:</strong> {_e(kit.strategy.positioning)}</p>"
        f"<p><strong>Concept:</strong> {_e(kit.strategy.concept)}</p><ul>{messages}</ul>"
        f'<h3>Channel plans</h3><p class="note">{_e(kit.channel_plan_label)}</p><ul>{plans}</ul>'
    )


def _image(kit: CampaignKit, asset_id: str, files: Mapping[str, bytes]) -> str:
    parts: list[str] = []
    prompt = next((p for p in kit.image_prompts if p.asset_id == asset_id), None)
    if prompt:
        parts.append(f'<p class="note">Image prompt: {_e(prompt.prompt)}</p>')
    image = next((i for i in kit.images if i.asset_id == asset_id), None)
    if image and image.file in files:
        encoded = base64.b64encode(files[image.file]).decode("ascii")
        parts.append(f'<img src="data:image/png;base64,{encoded}" alt="{_e(image.alt_text)}">')
        parts.append(f'<p class="note">{_e(image.label)}</p>')
    return "".join(parts)


def _assets(kit: CampaignKit, files: Mapping[str, bytes]) -> str:
    cards: list[str] = []
    for item in kit.assets:
        asset = item.asset
        fields = "".join(
            f'<p class="label">{_e(name)}</p><p class="copy">{_e(text)}</p>'
            for name, text in asset.fields.items()
        )
        warnings = "".join(f'<p class="note">Warning: {_e(w.message)}</p>' for w in item.warnings)
        title = f"{_e(asset.asset_id)} ({_e(CHANNEL_TITLES[asset.channel])})"
        image = _image(kit, asset.asset_id, files)
        cards.append(f'<article class="card"><h3>{title}</h3>{fields}{warnings}{image}</article>')
    return f"<h2>Assets</h2>{''.join(cards)}"


def _appendix(kit: CampaignKit) -> str:
    if not kit.verified:
        return "<h2>Claims appendix</h2><p>Claims in this kit were not verified.</p>"
    if not kit.claims:
        return "<h2>Claims appendix</h2><p>This kit makes no factual claims.</p>"
    headers = ("Claim", "Text", "Type", "Verdict", "Evidence")
    return f"<h2>Claims appendix</h2>{_table(headers, [_claim_row(c) for c in kit.claims])}"


def _ledger(kit: CampaignKit) -> str:
    if not kit.ledger.issues:
        return ""
    rows = [
        f"<tr><td>{_e(i.id)}</td><td>{_e(i.asset_id)}</td><td>{_e(i.status)}</td>"
        f"<td>{_e(i.problem)}</td></tr>"
        for i in kit.ledger.issues
    ]
    return f"<h2>Issue ledger</h2>{_table(('Issue', 'Asset', 'Status', 'Problem'), rows)}"


def _list(title: str, items: list[str]) -> str:
    if not items:
        return ""
    return f"<h2>{_e(title)}</h2><ul>{''.join(f'<li>{_e(item)}</li>' for item in items)}</ul>"


def render_html(kit: CampaignKit, image_files: Mapping[str, bytes] | None = None) -> str:
    """The whole kit as a page with no external resources."""
    accent = kit.brand_colors[0].hex if kit.brand_colors else "#3F5B45"
    status_class = "status approved" if kit.status == "approved" else "status"
    body = "".join(
        [
            f"<h1>{_e(kit.brand_name)}: {_e(kit.product_name)}</h1>",
            f'<p class="{status_class}">{_e(status_line(kit))}</p>',
            _strategy(kit),
            _assets(kit, image_files or {}),
            _list("Gaps", [f"{gap.asset_id}: {gap.reason}" for gap in kit.gaps]),
            _appendix(kit),
            _ledger(kit),
            _list("Research gaps", kit.research_gaps),
            f"<h2>Cost</h2><p>${kit.cost.total_usd:.4f} of a ${kit.cost.cap_usd:.2f} cap</p>",
        ]
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{_POLICY}">'
        f"<title>{_e(kit.product_name)} campaign kit</title>"
        f"<style>{_STYLE.replace('__ACCENT__', accent)}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )
