import pytest

from adlantis.config import Settings
from adlantis.tools import ToolRegistry, build_default_registry
from tests.fakes import MockHTTP, respond
from tests.tools.test_base import EchoTool


def test_default_registry_without_tavily_key(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="adlantis.tools.registry")
    with build_default_registry(Settings()) as registry:
        assert registry.names == ["fetch_url"]
    assert "web_search disabled" in caplog.text


def test_default_registry_with_tavily_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    with build_default_registry(Settings()) as registry:
        assert registry.names == ["web_search", "fetch_url"]
        assert "web_search" in registry
        assert len(registry) == 2


def test_tools_share_one_client_and_expose_schemas() -> None:
    http = MockHTTP(respond())
    registry = build_default_registry(Settings(), client=http.client)
    for tool in registry:
        assert tool._client is http.client
        schema = tool.parameters_schema()
        assert schema["type"] == "object"
        assert tool.description
    registry.close()
    assert not http.client.is_closed  # caller-owned client is left open


def test_owned_client_closed() -> None:
    registry = build_default_registry(Settings())
    client = registry.get("fetch_url")._client
    registry.close()
    assert client.is_closed


def test_run_dispatches_by_name() -> None:
    registry = ToolRegistry([EchoTool(sleep=lambda _s: None)])
    result = registry.run("echo", {"text": "hi"})
    assert result.ok
    assert result.data == {"echo": "hi"}


def test_unknown_tool_is_a_recoverable_result() -> None:
    registry = ToolRegistry([EchoTool()])
    result = registry.run("google", {"q": "x"})
    assert not result.ok
    assert result.error == "Unknown tool 'google'. Available: ['echo']"


def test_duplicate_names_rejected() -> None:
    with pytest.raises(ValueError, match="already registered"):
        ToolRegistry([EchoTool(), EchoTool()])
