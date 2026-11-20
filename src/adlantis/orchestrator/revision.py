"""Applies a copywriter's proposed edits, allowing only small, exact, traceable changes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

from adlantis.rules.text import REFERENCE_ID, contains_text
from adlantis.schemas.channels import SECTION_CHANNELS
from adlantis.schemas.copy import AssetEdit, CampaignAsset, Citation, RevisionPlan

MAX_EDIT_CHARS = 300


class EditResult(NamedTuple):
    """The revised asset and what happened to each proposed edit."""

    asset: CampaignAsset
    applied: int
    refused: list[str]


def _refusal(
    edit: AssetEdit,
    fields: dict[str, str],
    issue_ids: set[str],
    allowed: frozenset[str],
    required: Mapping[str, str],
) -> str | None:
    if edit.issue_id not in issue_ids:
        return "does not address an open issue"
    text = fields.get(edit.field)
    if text is None:
        return "names an unknown field"
    if not edit.find:
        return "has nothing to replace"
    if len(edit.find) > MAX_EDIT_CHARS:
        return "is too large to be a targeted edit"
    if text.count(edit.find) != 1:
        return "must match exactly one passage"
    if not set(edit.references) <= allowed:
        return "cites an unusable source"
    revised = text.replace(edit.find, edit.replace, 1)
    if not revised.strip():
        return "would leave the field empty"
    name = required.get(edit.field)
    if name and contains_text(text, name) and not contains_text(revised, name):
        return "would remove the required product name"
    return None


def _carried(citations: list[Citation], text: str, edit: AssetEdit) -> list[Citation]:
    """New citations for statements the edit shortened or reworded, so their sources survive.

    A statement the edit replaced completely is not carried: its sources proved the old text.
    """
    start = text.index(edit.find)
    end = start + len(edit.find)
    carried: list[Citation] = []
    for citation in citations:
        first = text.find(citation.text)
        last = first + len(citation.text)
        if first < 0 or end <= first or last <= start or (start <= first and last <= end):
            continue
        kept = text[first : max(first, start)] + edit.replace + text[min(last, end) : last]
        if any(char.isalnum() for char in kept):
            references = sorted({*citation.references, *edit.references})
            carried.append(Citation(text=kept.strip(), references=references))
    return carried


def apply_edits(
    asset: CampaignAsset,
    plan: RevisionPlan,
    issue_ids: set[str],
    allowed: frozenset[str],
    required: Mapping[str, str] | None = None,
) -> EditResult:
    """Apply each acceptable edit in order. The original asset is never changed.

    `required` maps a field to a name that an edit must not remove from it.
    """
    fields = dict(asset.fields)
    citations = list(asset.citations)
    applied = 0
    refused: list[str] = []
    section_sources = set(asset.references) if asset.channel in SECTION_CHANNELS else set()
    for edit in plan.edits:
        reason = _refusal(edit, fields, issue_ids, allowed, required or {})
        if reason:
            refused.append(f"{edit.issue_id}: {reason}")
            continue
        citations += _carried(citations, fields[edit.field], edit)
        fields[edit.field] = fields[edit.field].replace(edit.find, edit.replace, 1)
        if asset.channel in SECTION_CHANNELS:  # plan sections cite their sources as a whole
            named = set(REFERENCE_ID.findall(edit.replace)) & allowed
            section_sources |= set(edit.references) | named
        elif edit.replace.strip() and edit.references:
            citations.append(Citation(text=edit.replace, references=edit.references))
        applied += 1
    kept = [c for c in citations if any(contains_text(t, c.text) for t in fields.values())]
    revised = asset.model_copy(
        update={
            "fields": fields,
            "citations": kept,
            "references": sorted({r for c in kept for r in c.references} | section_sources),
        }
    )
    return EditResult(revised, applied, refused)
