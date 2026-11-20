"""Pages that wrap their content in a form are readable; ordinary forms stay out."""

from adlantis.tools.extract import html_to_text

STORY = "Specialty coffee drinking stayed near its record high this year, the survey found. " * 4
WRAPPED = f"""<html><head><title>Report</title></head><body><form id="Form" method="post">
<input type="hidden" name="__VIEWSTATE" value="abc"><h1>The report</h1><p>{STORY}</p>
</form></body></html>"""


def test_content_inside_a_page_wrapping_form_is_read() -> None:
    page = html_to_text(WRAPPED)
    assert STORY.strip() in page.text
    assert page.heading == "The report"


def test_ordinary_form_on_a_full_page_stays_out() -> None:
    html = f"<body><p>{STORY}</p><form><p>Join our mailing list</p></form></body>"
    assert "mailing list" not in html_to_text(html).text


def test_hidden_text_inside_a_wrapping_form_is_still_dropped() -> None:
    html = WRAPPED.replace("<h1>", '<div style="display:none">Secret note</div><h1>')
    page = html_to_text(html)
    assert "Secret note" not in page.text
    assert page.hidden_blocks == 1


def test_chrome_inside_a_wrapping_form_is_still_dropped() -> None:
    html = WRAPPED.replace("<h1>", "<nav>Site menu</nav><h1>")
    assert "Site menu" not in html_to_text(html).text


def test_form_controls_inside_a_wrapping_form_are_dropped() -> None:
    html = WRAPPED.replace("<h1>", "<textarea>Typed text</textarea><button>Send</button><h1>")
    text = html_to_text(html).text
    assert "Typed text" not in text and "Send" not in text


def test_page_with_only_a_short_form_returns_its_text() -> None:
    assert html_to_text("<body><form><p>Sign in</p></form></body>").text == "Sign in"
