from adlantis.tools.extract import html_to_text

PAGE = """<!doctype html><html><head>
<title>  Solid-State
 Batteries &amp; You </title>
<style>body { color: red }</style><script>track()</script>
</head><body>
<header><nav><a href="/">Home</a> | <a href="/about">About</a></nav></header>
<h1>Solid-state batteries</h1>
<p>They replace the <b>liquid</b> electrolyte with a solid one.</p>
<ul><li>Safer</li><li>Denser</li></ul>
<aside>Subscribe to our newsletter!</aside>
<footer>© 2026 Example</footer>
<noscript>Enable JS</noscript>
</body></html>"""


def test_title_and_body_text_without_chrome() -> None:
    title, text, heading, _hidden = html_to_text(PAGE)
    assert heading == "Solid-state batteries"
    assert title == "Solid-State Batteries & You"
    assert text.splitlines() == [
        "Solid-state batteries",
        "They replace the liquid electrolyte with a solid one.",
        "Safer",
        "Denser",
    ]
    for junk in ("track()", "color: red", "Home", "newsletter", "© 2026", "Enable JS"):
        assert junk not in text


def test_main_content_preferred_when_substantial() -> None:
    body = "Real article text. " * 20
    html = f"<body><div>Sidebar links and promos</div><article><p>{body}</p></article></body>"
    text = html_to_text(html).text
    assert "Sidebar" not in text
    assert text.startswith("Real article text.")


def test_tiny_main_falls_back_to_whole_page() -> None:
    html = "<body><main><p>Hi</p></main><div><p>Most of the content lives here.</p></div></body>"
    text = html_to_text(html).text
    assert "Most of the content lives here." in text


def test_unclosed_and_nested_skip_tags() -> None:
    text = html_to_text("<p>keep</p><nav><nav>drop</nav>still drop</nav><p>keep too").text
    assert text.splitlines() == ["keep", "keep too"]


def test_first_visible_heading_skips_chrome() -> None:
    page = html_to_text("<header><h1>Site Name</h1></header><h2> Real  Topic </h2><h1>Later</h1>")
    assert page.heading == "Real Topic"
