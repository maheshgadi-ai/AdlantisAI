import httpx
import pytest
from pydantic import BaseModel

from adlantis.tools.base import ToolError, TransientToolError
from adlantis.tools.http import USER_AGENT, HttpTool, check_status
from tests.fakes import MockHTTP, respond


class PingArgs(BaseModel):
    url: str


class PingTool(HttpTool[PingArgs]):
    name = "ping"
    description = "GET a URL"
    args_schema = PingArgs

    def _run(self, args: PingArgs) -> int:
        return self._send("GET", args.url).status_code


def make(*responses, sleeps: list | None = None) -> tuple[PingTool, MockHTTP]:
    http = MockHTTP(respond(*responses))
    sleeps = [] if sleeps is None else sleeps
    return PingTool(client=http.client, sleep=sleeps.append), http


def test_user_agent_identifies_project_with_contact_url() -> None:
    assert USER_AGENT.startswith("AdlantisAI/")
    assert "https://github.com/maheshgadi-ai/AdlantisAI" in USER_AGENT
    assert "bot" in USER_AGENT
    tool, http = make(httpx.Response(200))
    tool.run({"url": "https://example.org"})
    assert http.last.headers["User-Agent"] == USER_AGENT


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_retryable_status_is_transient(code: int) -> None:
    with pytest.raises(TransientToolError):
        check_status(httpx.Response(code, request=httpx.Request("GET", "https://x")), "t")


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422, 432, 433])
def test_client_errors_are_permanent(code: int) -> None:
    with pytest.raises(ToolError) as info:
        check_status(httpx.Response(code, request=httpx.Request("GET", "https://x")), "t")
    assert not isinstance(info.value, TransientToolError)


def test_retry_after_header_parsed_and_capped() -> None:
    req = httpx.Request("GET", "https://x")
    with pytest.raises(TransientToolError) as info:
        check_status(httpx.Response(429, headers={"Retry-After": "7"}, request=req), "t")
    assert info.value.retry_after == 7.0
    with pytest.raises(TransientToolError) as info:
        check_status(httpx.Response(429, headers={"Retry-After": "9999"}, request=req), "t")
    assert info.value.retry_after == 30.0


def test_retry_after_raises_backoff_delay() -> None:
    sleeps: list[float] = []
    tool, _ = make(
        httpx.Response(429, headers={"Retry-After": "4"}), httpx.Response(200), sleeps=sleeps
    )
    result = tool.run({"url": "https://example.org"})
    assert result.ok
    assert sleeps == [4.0]  # larger than the 0.5 s base backoff


@pytest.mark.parametrize(
    "error", [httpx.ConnectTimeout("slow"), httpx.ConnectError("refused"), httpx.ReadError("eof")]
)
def test_transport_failures_retried_then_reported(error: Exception) -> None:
    tool, http = make(error, error, error)
    result = tool.run({"url": "https://example.org"})
    assert not result.ok
    assert result.attempts == 3
    assert len(http.requests) == 3


def test_error_message_includes_status_and_body() -> None:
    tool, _ = make(httpx.Response(404, text="no such page"))
    result = tool.run({"url": "https://example.org/missing"})
    assert result.error == "ping: HTTP 404 - no such page"
