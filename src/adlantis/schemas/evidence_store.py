"""The evidence store: every source a run has seen, under IDs that never change."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adlantis.schemas.evidence import utc_now
from adlantis.schemas.quality import SourceRating

EvidenceStatus = Literal["usable", "quarantined"]
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "ref_src"}


def canonical_url(url: str) -> str:
    """A comparable form of a URL: no fragment, tracking parameters, or trailing slash."""
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS and not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    host = (parts.hostname or "").lower().removeprefix("www.")
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip("/"), urlencode(query), ""))


class EvidenceRecord(BaseModel):
    """One source excerpt. Records are immutable, so a citation always means the same text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^E-[1-9]\d*$")
    url: str
    canonical_url: str
    title: str
    excerpt: str
    content_hash: str
    tool: str
    retrieved_at: datetime = Field(default_factory=utc_now)
    published: str | None = None
    rating: SourceRating
    status: EvidenceStatus = "usable"
    injection_signals: tuple[str, ...] = ()
    hidden_blocks: int = Field(default=0, ge=0)


class EvidenceStore(BaseModel):
    """Append-only evidence. The same text from the same page always keeps its first ID."""

    model_config = ConfigDict(extra="forbid")

    records: list[EvidenceRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_run_in_order(self) -> EvidenceStore:
        expected = [f"E-{number}" for number in range(1, len(self.records) + 1)]
        if [record.id for record in self.records] != expected:
            raise ValueError("evidence IDs must run in order from E-1")
        return self

    def add(
        self,
        *,
        url: str,
        title: str,
        excerpt: str,
        tool: str,
        rating: SourceRating,
        published: str | None = None,
        injection_signals: tuple[str, ...] = (),
        hidden_blocks: int = 0,
    ) -> EvidenceRecord:
        """Store a source and return its record, reusing the record for repeated content."""
        canonical = canonical_url(url)
        content_hash = hashlib.sha256(f"{title}\n{excerpt}".encode()).hexdigest()
        for record in self.records:
            if (record.canonical_url, record.content_hash) == (canonical, content_hash):
                return record
        record = EvidenceRecord(
            id=f"E-{len(self.records) + 1}",
            url=url,
            canonical_url=canonical,
            title=title,
            excerpt=excerpt,
            content_hash=content_hash,
            tool=tool,
            published=published,
            rating=rating,
            status="quarantined" if injection_signals else "usable",
            injection_signals=injection_signals,
            hidden_blocks=hidden_blocks,
        )
        self.records.append(record)
        return record

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        """The record with this ID, if any."""
        return next((r for r in self.records if r.id == evidence_id), None)

    def usable(self) -> list[EvidenceRecord]:
        """Records that may be shown to models and cited."""
        return [r for r in self.records if r.status == "usable"]

    def quarantined(self) -> list[EvidenceRecord]:
        """Records kept for audit only, because they tried to instruct the system."""
        return [r for r in self.records if r.status == "quarantined"]

    def usable_ids(self) -> frozenset[str]:
        """IDs that copy is allowed to cite."""
        return frozenset(r.id for r in self.usable())
