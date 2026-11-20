"""Fetch a web page and return its readable text.

The model chooses which URLs to fetch, so this tool guards against server-side
request forgery: only http(s), and every hop (including redirects) must resolve to
a public address. Downloads are capped in size.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, Field, HttpUrl

from adlantis.schemas.evidence import Evidence
from adlantis.schemas.titles import clean_title
from adlantis.tools.base import ToolError, TransientToolError
from adlantis.tools.extract import html_to_text
from adlantis.tools.http import EvidenceTool, check_status

Resolver = Callable[[str], list[str]]

_REDIRECTS = {301, 302, 303, 307, 308}
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_TEXT_TYPES = {"text/plain", "text/markdown"}


@dataclass(frozen=True)
class _Page:
    status: int
    location: str | None = None
    mime: str = ""
    encoding: str = "utf-8"
    body: bytes = b""
    truncated: bool = False


class FetchUrlArgs(BaseModel):
    """Arguments for `fetch_url`."""

    url: HttpUrl = Field(description="Full http(s) URL of the page to read.")
    max_chars: int = Field(default=8000, ge=500, le=50_000)


class FetchUrlTool(EvidenceTool[FetchUrlArgs]):
    """Read one web page (HTML or plain text) and return its main text."""

    name = "fetch_url"
    description = (
        "Download a public web page and return its readable text (navigation, scripts, and "
        "styling removed). Use it to read a promising search result in full."
    )
    args_schema = FetchUrlArgs
    cache_version: ClassVar[int] = 2  # page-wrapping forms are now read
    timeout_seconds: ClassVar[float] = 20.0
    max_bytes: ClassVar[int] = 2_000_000
    max_redirects: ClassVar[int] = 5

    def __init__(self, *, resolver: Resolver | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._resolve = resolver or resolve_host

    def _run(self, args: FetchUrlArgs) -> list[Evidence]:
        url = str(args.url)
        for _ in range(self.max_redirects + 1):
            self._check_public(url)
            page = self._get(url)
            if page.status in _REDIRECTS and page.location:
                url = urljoin(url, page.location)
                continue
            return [self._to_evidence(url, page, args.max_chars)]
        raise ToolError(f"{self.name}: too many redirects")

    def _get(self, url: str) -> _Page:
        try:
            with self._client.stream("GET", url, timeout=self.timeout_seconds) as response:
                if response.status_code in _REDIRECTS:
                    return _Page(response.status_code, location=response.headers.get("Location"))
                if not response.is_success:
                    response.read()
                    check_status(response, self.name)
                mime = _mime(response.headers.get("Content-Type", ""))
                if mime and mime not in _HTML_TYPES | _TEXT_TYPES:
                    raise ToolError(f"{self.name}: unsupported content type {mime!r}")
                body, truncated = _read_capped(response, self.max_bytes)
                return _Page(
                    response.status_code,
                    mime=mime,
                    encoding=response.charset_encoding or "utf-8",
                    body=body,
                    truncated=truncated,
                )
        except httpx.TimeoutException as exc:
            raise TransientToolError(f"{self.name}: request timed out") from exc
        except httpx.TransportError as exc:
            raise TransientToolError(f"{self.name}: connection failed ({exc})") from exc

    def _check_public(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ToolError(f"{self.name}: only http(s) URLs are allowed")
        try:
            addresses = self._resolve(parts.hostname)
        except OSError as exc:
            raise ToolError(f"{self.name}: cannot resolve {parts.hostname}") from exc
        for addr in addresses:
            if not ipaddress.ip_address(addr).is_global:
                raise ToolError(f"{self.name}: refusing non-public address for {parts.hostname}")

    def _to_evidence(self, url: str, page: _Page, max_chars: int) -> Evidence:
        try:
            raw = page.body.decode(page.encoding, errors="replace")
        except LookupError:  # unknown charset name in the header
            raw = page.body.decode("utf-8", errors="replace")
        if page.mime in _HTML_TYPES or not page.mime:
            title, text, heading, hidden = html_to_text(raw)
        else:
            title, text, heading, hidden = "", raw.strip(), "", 0
        if not text:
            raise ToolError(f"{self.name}: no readable text at {url}")
        metadata = {"content_type": page.mime or "unknown"}
        if hidden:
            metadata["hidden_blocks"] = str(hidden)
        if page.truncated or len(text) > max_chars:
            metadata["truncated"] = "true"
        return Evidence(
            source_url=url, title=clean_title(title, url, heading, text), snippet=text[:max_chars],
            tool=self.name,
            metadata=metadata,
        )  # fmt: skip


def resolve_host(host: str) -> list[str]:
    """All IP addresses `host` resolves to (IP literals resolve to themselves)."""
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


def _mime(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _read_capped(response: httpx.Response, limit: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size >= limit:
            return b"".join(chunks)[:limit], True
    return b"".join(chunks), False
