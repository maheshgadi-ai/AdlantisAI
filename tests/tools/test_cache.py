import json
from pathlib import Path

import httpx
import pytest

from adlantis.config import Settings
from adlantis.schemas import Evidence
from adlantis.tools import ToolCache, WebSearchTool, build_default_registry
from adlantis.tools.cache import cache_key
from tests.fakes import MockHTTP, respond

PAYLOAD = {"results": [{"url": "https://example.org/t", "title": "T", "content": "Text"}]}


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_key_is_order_independent_and_tool_specific() -> None:
    assert cache_key("t", {"a": 1, "b": 2}) == cache_key("t", {"b": 2, "a": 1})
    assert cache_key("t", {"a": 1}) != cache_key("u", {"a": 1})
    assert cache_key("t", {"a": 1}) != cache_key("t", {"a": 2})


def test_put_get_and_expiry(tmp_path: Path) -> None:
    clock = Clock()
    cache = ToolCache(tmp_path, ttl_seconds=60, clock=clock)
    assert cache.get("t", {"q": "x"}) is None
    cache.put("t", {"q": "x"}, [{"v": 1}])
    assert cache.get("t", {"q": "x"}) == [{"v": 1}]
    clock.now += 61
    assert cache.get("t", {"q": "x"}) is None


def test_corrupt_or_foreign_entries_are_misses(tmp_path: Path) -> None:
    cache = ToolCache(tmp_path, ttl_seconds=60)
    cache.put("t", {"q": "x"}, [1])
    (path,) = (tmp_path / "t").glob("*.json")
    path.write_text("{not json")
    assert cache.get("t", {"q": "x"}) is None
    path.write_text(json.dumps({"format": 999, "created_at": 0, "data": [1]}))
    assert cache.get("t", {"q": "x"}) is None


def test_unwritable_directory_does_not_raise(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    ToolCache(blocker, ttl_seconds=60).put("t", {"q": "x"}, [1])  # logged, not raised


def make_tool(tmp_path: Path, *responses) -> tuple[WebSearchTool, MockHTTP]:
    http = MockHTTP(respond(*responses))
    cache = ToolCache(tmp_path, ttl_seconds=3600)
    return WebSearchTool(api_key="k", client=http.client, cache=cache, sleep=lambda _s: None), http


def test_second_identical_call_served_from_cache(tmp_path: Path) -> None:
    tool, http = make_tool(tmp_path, httpx.Response(200, json=PAYLOAD))
    first = tool.run({"query": "T"})
    second = tool.run({"query": "T"})

    assert len(http.requests) == 1
    assert (first.cached, second.cached) == (False, True)
    assert isinstance(second.data[0], Evidence)  # rebuilt as typed objects
    assert second.data[0].source_url == first.data[0].source_url


def test_defaults_are_part_of_the_key(tmp_path: Path) -> None:
    tool, http = make_tool(
        tmp_path, httpx.Response(200, json=PAYLOAD), httpx.Response(200, json=PAYLOAD)
    )
    tool.run({"query": "T"})
    tool.run({"query": "T", "max_results": 5})  # same as the default → cache hit
    tool.run({"query": "T", "max_results": 3})  # different → miss
    assert len(http.requests) == 2


def test_failures_are_not_cached(tmp_path: Path) -> None:
    tool, http = make_tool(tmp_path, httpx.Response(404), httpx.Response(200, json=PAYLOAD))
    assert not tool.run({"query": "T"}).ok
    assert tool.run({"query": "T"}).ok
    assert len(http.requests) == 2


def test_registry_uses_cache_only_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with build_default_registry(Settings()) as registry:
        assert all(tool._cache is None for tool in registry)
    monkeypatch.setenv("TOOL_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("TOOL_CACHE_TTL_HOURS", "2")
    with build_default_registry(Settings()) as registry:
        caches = {id(tool._cache) for tool in registry}
        assert len(caches) == 1  # shared
        cache = registry.get("fetch_url")._cache
        assert cache.directory == tmp_path
        assert cache.ttl_seconds == 7200


def test_empty_results_are_not_cached(tmp_path: Path) -> None:
    empty = {"results": []}
    tool, http = make_tool(
        tmp_path, httpx.Response(200, json=empty), httpx.Response(200, json=PAYLOAD)
    )
    assert tool.run({"query": "T"}).data == []
    assert tool.run({"query": "T"}).data  # second call went to the network
    assert len(http.requests) == 2


def test_cache_version_bump_invalidates_old_entries(tmp_path: Path) -> None:
    class SearchV2(WebSearchTool):
        cache_version = 2

    tool, _ = make_tool(tmp_path, httpx.Response(200, json=PAYLOAD))
    tool.run({"query": "T"})
    http = MockHTTP(respond(httpx.Response(200, json=PAYLOAD)))
    newer = SearchV2(
        api_key="k",
        client=http.client,
        cache=ToolCache(tmp_path, ttl_seconds=3600),
        sleep=lambda _s: None,
    )
    result = newer.run({"query": "T"})
    assert not result.cached
    assert len(http.requests) == 1
