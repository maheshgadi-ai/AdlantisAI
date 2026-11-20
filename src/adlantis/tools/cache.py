"""Optional on-disk cache of successful tool results.

Off unless `TOOL_CACHE_DIR` is set. Useful for re-running the same brief while
developing prompts, and it keeps repeat queries off the search API. Only
successful results are cached; entries expire after `TOOL_CACHE_TTL_HOURS`.

Layout: `<dir>/<tool>/<sha256>.json`. The key covers the tool name, its arguments
(canonical JSON), and a format version. It never includes API keys.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CACHE_FORMAT = 1


class ToolCache:
    """A directory of JSON files keyed by tool name and arguments."""

    def __init__(
        self, directory: Path, *, ttl_seconds: float, clock: Callable[[], float] = time.time
    ) -> None:
        self.directory = Path(directory)
        self.ttl_seconds = ttl_seconds
        self._clock = clock

    def get(self, tool: str, args: dict[str, Any]) -> Any | None:
        """Return cached result data, or None on a miss, an expired entry, or a bad file."""
        path = self._path(tool, args)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.warning("ignoring unreadable cache entry", extra={"path": str(path)})
            return None
        if entry.get("format") != CACHE_FORMAT:
            return None
        if self._clock() - entry.get("created_at", 0) > self.ttl_seconds:
            return None
        return entry.get("data")

    def put(self, tool: str, args: dict[str, Any], data: Any) -> None:
        """Store result data (JSON-serializable). Failures are logged, never raised."""
        path = self._path(tool, args)
        entry = {"format": CACHE_FORMAT, "created_at": self._clock(), "tool": tool, "args": args,
                 "data": data}  # fmt: skip
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(entry, handle, ensure_ascii=False)
            os.replace(tmp, path)  # atomic: readers never see a half-written file
        except (OSError, TypeError, ValueError):
            logger.warning("could not write cache entry", extra={"path": str(path)}, exc_info=True)

    def _path(self, tool: str, args: dict[str, Any]) -> Path:
        return self.directory / tool / f"{cache_key(tool, args)}.json"


def cache_key(tool: str, args: dict[str, Any]) -> str:
    """Stable hash of (format, tool, args); argument order doesn't matter."""
    canonical = json.dumps([CACHE_FORMAT, tool, args], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
