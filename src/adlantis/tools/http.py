"""Shared HTTP plumbing for tools: client setup and error classification."""

from __future__ import annotations

from typing import Any, ClassVar, TypeVar

import httpx
from pydantic import BaseModel

from adlantis import __version__
from adlantis.schemas.evidence import Evidence
from adlantis.tools.base import BaseTool, ToolError, TransientToolError

# Identify the client and give site operators a way to learn what it is.
USER_AGENT = (
    f"AdlantisAI/{__version__} (https://github.com/maheshgadi-ai/AdlantisAI; research bot) "
    f"httpx/{httpx.__version__}"
)
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_MAX_RETRY_AFTER_SECONDS = 30.0

ArgsT = TypeVar("ArgsT", bound=BaseModel)


def default_client() -> httpx.Client:
    """An httpx client with the project User-Agent. Timeouts are set per request."""
    return httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=False)


class HttpTool(BaseTool[ArgsT]):
    """A tool that talks HTTP. Subclasses call `self._send(...)`."""

    timeout_seconds: ClassVar[float] = 15.0

    def __init__(self, *, client: httpx.Client | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client = client or default_client()

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send a request and turn failures into `ToolError` / `TransientToolError`."""
        kwargs.setdefault("timeout", self.timeout_seconds)
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise TransientToolError(f"{self.name}: request timed out") from exc
        except httpx.TransportError as exc:
            raise TransientToolError(f"{self.name}: connection failed ({exc})") from exc
        check_status(response, self.name)
        return response


class EvidenceTool(HttpTool[ArgsT]):
    """An HTTP tool whose result data is a list of `Evidence` (all research tools)."""

    def _load_cached(self, data: Any) -> list[Evidence]:
        return [Evidence.model_validate(item) for item in data]


def check_status(response: httpx.Response, tool: str) -> None:
    """Raise for non-2xx responses: retryable codes as transient, the rest as permanent."""
    if response.is_success:
        return
    code = response.status_code
    detail = response.text[:200].strip()
    message = f"{tool}: HTTP {code}" + (f" - {detail}" if detail else "")
    if code in _RETRYABLE_STATUS:
        raise TransientToolError(message, retry_after=_retry_after(response), status=code)
    raise ToolError(message)


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    try:
        return min(float(value), _MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        return None  # absent, or an HTTP date (rare for APIs); use normal backoff
