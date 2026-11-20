"""A timeline of one run, written as JSON lines as it happens."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from adlantis.schemas.research import ResearchResult

RunStatus = Literal["started", "finished", "failed", "skipped"]
MAX_DETAIL_CHARS = 300
QUARANTINE_STAGE = "research:withheld"
_SECRET = re.compile(r"\b(?:sk|pk|tvly|lf)-[A-Za-z0-9_-]{8,}")


class RunEvent(BaseModel):
    """One step of a run."""

    at: datetime
    stage: str
    status: RunStatus
    detail: str = ""
    spent_usd: float = 0.0


def record_research_issues(log: RunLog, research: ResearchResult) -> None:
    """Log every failed tool call, refused call, and source withheld as a possible injection."""
    for failure in research.stats.tool_failures:
        log.record(f"tool:{failure.tool}", "failed", f"{failure.cause}: {failure.target}")
    for reason in research.stats.refused_calls:
        log.record("tool:refused", "skipped", reason)
    for record in research.evidence.quarantined():
        signals = ", ".join(record.injection_signals)
        log.record(QUARANTINE_STAGE, "skipped", f"{record.id} ({signals}): {record.url}")


def redact(text: str, limit: int = MAX_DETAIL_CHARS) -> str:
    """Text safe to store: shortened, with anything shaped like a key removed."""
    return _SECRET.sub("[removed]", text)[:limit]


def utc_now() -> datetime:
    """The current time in UTC."""
    return datetime.now(UTC)


class RunLog:
    """Records events in memory and, when given a path, on disk. Safe across threads."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        spent: Callable[[], float] = lambda: 0.0,
        on_event: Callable[[RunEvent], None] | None = None,
    ) -> None:
        self.path = path
        self.events: list[RunEvent] = []
        self._clock = clock
        self._spent = spent
        self._on_event = on_event
        self._lock = threading.Lock()

    def record(self, stage: str, status: RunStatus, detail: str = "") -> RunEvent:
        """Add one event. Details are shortened, and anything shaped like a key is removed."""
        clean = redact(detail)
        event = RunEvent(
            at=self._clock(),
            stage=stage,
            status=status,
            detail=clean,
            spent_usd=round(self._spent(), 6),
        )
        with self._lock:
            self.events.append(event)
            if self.path is not None:
                with self.path.open("a", encoding="utf-8") as file:
                    file.write(event.model_dump_json() + "\n")
        if self._on_event is not None:
            self._on_event(event)
        return event
