from typing import ClassVar

import httpx
import pytest

from adlantis.tools.fetch_url import FetchUrlTool
from tests.fakes import MockHTTP

HTML = "<html><head><title>Example Domain</title></head><body><p>Hello, reader.</p></body></html>"
PUBLIC = {"example.org": ["93.184.215.14"], "cdn.example.net": ["2606:4700::6810:84e5"]}


def resolver(table: dict[str, list[str]]):
    def resolve(host: str) -> list[str]:
        if host not in table:
            raise OSError("unknown host")
        return table[host]

    return resolve


def make(handler, table=PUBLIC, tool_cls=FetchUrlTool) -> tuple[FetchUrlTool, MockHTTP]:
    http = MockHTTP(handler)
    tool = tool_cls(client=http.client, resolver=resolver(table), sleep=lambda _s: None)
    return tool, http


def html_page(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"Content-Type": "text/html; charset=utf-8"}, text=HTML)


def test_reads_html_page() -> None:
    tool, http = make(html_page)
    result = tool.run({"url": "https://example.org/"})

    assert result.ok, result.error
    (evidence,) = result.data
    assert evidence.title == "Example Domain"
    assert evidence.snippet == "Hello, reader."
    assert evidence.source_url == "https://example.org/"
    assert evidence.tool == "fetch_url"
    assert evidence.metadata == {"content_type": "text/html"}
    assert http.last.method == "GET"


def test_plain_text_and_declared_charset() -> None:
    body = "Résumé of results".encode("latin-1")
    tool, _ = make(
        lambda _r: httpx.Response(
            200, headers={"Content-Type": "text/plain; charset=latin-1"}, content=body
        )
    )
    (evidence,) = tool.run({"url": "https://example.org/notes.txt"}).data
    assert evidence.snippet == "Résumé of results"
    assert evidence.title == "Résumé of results"  # no <title>: a title-like first line


def test_unsupported_content_type_rejected() -> None:
    tool, _ = make(
        lambda _r: httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=b"%PDF")
    )
    result = tool.run({"url": "https://example.org/paper.pdf"})
    assert not result.ok
    assert "unsupported content type 'application/pdf'" in (result.error or "")


def test_max_chars_truncates_and_flags() -> None:
    long = "<p>" + "word " * 2000 + "</p>"
    tool, _ = make(lambda _r: httpx.Response(200, headers={"Content-Type": "text/html"}, text=long))
    (evidence,) = tool.run({"url": "https://example.org/", "max_chars": 500}).data
    assert len(evidence.snippet) == 500
    assert evidence.metadata["truncated"] == "true"


def test_download_size_capped() -> None:
    class SmallCap(FetchUrlTool):
        max_bytes: ClassVar[int] = 1000

    big = "<p>" + "x" * 10_000 + "</p>"
    tool, _ = make(
        lambda _r: httpx.Response(200, headers={"Content-Type": "text/html"}, text=big),
        tool_cls=SmallCap,
    )
    (evidence,) = tool.run({"url": "https://example.org/"}).data
    assert len(evidence.snippet) < 1000
    assert evidence.metadata["truncated"] == "true"


def test_follows_redirect_to_public_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.org":
            return httpx.Response(301, headers={"Location": "https://cdn.example.net/page"})
        return html_page(request)

    tool, http = make(handler)
    (evidence,) = tool.run({"url": "https://example.org/old"}).data
    assert evidence.source_url == "https://cdn.example.net/page"
    assert [r.url.host for r in http.requests] == ["example.org", "cdn.example.net"]


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "fc00::1"]
)
def test_private_addresses_refused_before_any_request(address: str) -> None:
    tool, http = make(html_page, table={"internal.example": [address]})
    result = tool.run({"url": "http://internal.example/admin"})
    assert not result.ok
    assert "non-public address" in (result.error or "")
    assert http.requests == []


def test_redirect_into_private_network_refused() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://metadata.internal/latest"})

    table = {**PUBLIC, "metadata.internal": ["169.254.169.254"]}
    tool, http = make(handler, table=table)
    result = tool.run({"url": "https://example.org/"})
    assert not result.ok
    assert "non-public address" in (result.error or "")
    assert len(http.requests) == 1  # never contacted the internal host


def test_redirect_loop_stops() -> None:
    tool, http = make(lambda _r: httpx.Response(302, headers={"Location": "/again"}))
    result = tool.run({"url": "https://example.org/"})
    assert not result.ok
    assert "too many redirects" in (result.error or "")
    assert len(http.requests) == FetchUrlTool.max_redirects + 1


@pytest.mark.parametrize("url", ["ftp://example.org/file", "file:///etc/passwd", "not a url"])
def test_non_http_urls_rejected_by_validation(url: str) -> None:
    tool, http = make(html_page)
    assert not tool.run({"url": url}).ok
    assert http.requests == []


def test_unresolvable_host() -> None:
    tool, _ = make(html_page, table={})
    result = tool.run({"url": "https://nowhere.invalid/"})
    assert not result.ok
    assert "cannot resolve" in (result.error or "")


def test_http_errors_classified() -> None:
    tool, http = make(lambda _r: httpx.Response(404, text="gone"))
    result = tool.run({"url": "https://example.org/missing"})
    assert not result.ok
    assert "HTTP 404" in (result.error or "")
    assert len(http.requests) == 1  # 404 is not retried


def test_empty_page_reported() -> None:
    tool, _ = make(
        lambda _r: httpx.Response(200, headers={"Content-Type": "text/html"}, text="<script/>")
    )
    result = tool.run({"url": "https://example.org/"})
    assert not result.ok
    assert "no readable text" in (result.error or "")


def test_junk_html_title_falls_back_to_first_heading() -> None:
    html = "<title>Untitled Document</title><h1>Grid Storage Outlook</h1><p>Body text.</p>"
    tool, _ = make(lambda _r: httpx.Response(200, headers={"Content-Type": "text/html"}, text=html))
    (evidence,) = tool.run({"url": "https://example.org/page"}).data
    assert evidence.title == "Grid Storage Outlook"
