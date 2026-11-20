import pytest

from adlantis.schemas.titles import clean_title, is_junk_title, tidy_title, title_from_url

PDF = "https://www.iea.org/files/7ea38b60-3033/GlobalEVOutlook2025.pdf"


@pytest.mark.parametrize(
    "title",
    [
        "",
        "   ",
        "Untitled",
        "untitled document",
        "Untitled 3",
        "Microsoft .NET",
        ".NET",
        "Microsoft Word",
        "Microsoft Word - Final_Report_v2.docx",
        "PowerPoint Presentation",
        "Microsoft PowerPoint - deck.pptx",
        "Slide 1",
        "Document1",
        "Adobe Acrobat Pro",
        "report.pdf",
        "N/A",
    ],
)
def test_software_metadata_titles_are_junk(title: str) -> None:
    assert is_junk_title(title)


@pytest.mark.parametrize(
    "title",
    [
        "Global EV Outlook 2025",
        "Solid-state batteries: a review",
        "The Office of Science",
        "Word embeddings for retrieval",
        "Introduction to .NET performance tuning",
        "E-bike batteries - safety guide",
    ],
)
def test_real_titles_are_kept(title: str) -> None:
    assert not is_junk_title(title)
    assert clean_title(title, PDF) == title


def test_junk_suffix_removed_real_part_kept() -> None:
    title = "Batteries and Secure Energy Transitions - Microsoft .NET"
    assert clean_title(title, PDF) == "Batteries and Secure Energy Transitions"
    assert clean_title("Microsoft Word | Annual Report 2025", PDF) == "Annual Report 2025"


def test_heading_preferred_over_file_name() -> None:
    assert clean_title("Microsoft Word - draft.docx", PDF, heading=" Global  EV Outlook ") == (
        "Global EV Outlook"
    )
    # A junk heading doesn't count either.
    assert clean_title("Untitled", PDF, heading="Untitled") == "Global EV Outlook 2025"


def test_url_as_title_treated_as_missing() -> None:
    assert clean_title(PDF, PDF) == "Global EV Outlook 2025"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (PDF, "Global EV Outlook 2025"),
        (
            "https://example.org/reports/solid_state-batteries%20review.pdf",
            "solid state batteries review",
        ),
        (
            "https://example.org/docs/BatteriesAndSecureEnergyTransitions.pdf",
            "Batteries And Secure Energy Transitions",
        ),
        ("https://www.example.org/files/7ea38b60-3033-42a6.pdf", ""),  # an id, not a name
        ("https://www.example.org/", "example.org"),
    ],
)
def test_title_from_url(url: str, expected: str) -> None:
    assert title_from_url(url) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "Solid-State Batteries: The Technology of the 2030s but the ...",
            "Solid-State Batteries: The Technology of the 2030s",
        ),
        ("Advances in solid electrolytes \u2026", "Advances in solid electrolytes"),
        ("Market outlook -  ...", "Market outlook"),
        ("Results, ... ...", "Results"),
        ("Wait... what?", "Wait... what?"),  # only trailing ellipses go
        ("  Plain   title  ", "Plain title"),
    ],
)
def test_tidy_title(title: str, expected: str) -> None:
    assert tidy_title(title) == expected


def test_clean_title_also_drops_trailing_ellipsis() -> None:
    assert clean_title("Solid-state battery review ...", PDF) == "Solid-state battery review"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "Advances in solid-state batteries fabrication - ScienceDirect",
            "Advances in solid-state batteries fabrication",
        ),
        ("Climate review | Nature", "Climate review"),
        ("Solid-state battery - Wikipedia", "Solid-state battery"),
        ("Paper title - IEEE Xplore - arXiv.org", "Paper title"),
        ("Interfaces in SSBs - Springer Nature Link", "Interfaces in SSBs"),
        ("Nature", "Nature"),  # a lone name is kept: it might be the real title
        ("Nature-inspired electrolytes - review", "Nature-inspired electrolytes - review"),
    ],
)
def test_publisher_suffixes_stripped(title: str, expected: str) -> None:
    assert clean_title(title, PDF) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("[PDF] Solid-State Li-Metal Batteries", "Solid-State Li-Metal Batteries"),
        ("(PDF) Interfaces in solid electrolytes", "Interfaces in solid electrolytes"),
        ("PDF: Grid storage review", "Grid storage review"),
        ("[HTML] Battery basics", "Battery basics"),
        ("Grid storage: the role of the ...", "Grid storage: the role"),  # dangling words go
        ("Lithium metal anodes in the …", "Lithium metal anodes"),
        ("PDF readers compared", "PDF readers compared"),  # not a tag
    ],
)
def test_tidy_title_tags_and_truncation(title: str, expected: str) -> None:
    assert tidy_title(title) == expected


def test_fallback_order_heading_then_first_line_then_file_then_untitled() -> None:
    pdf_id = "https://inis.iaea.org/records/x/files/NL21V7636.pdf"
    assert clean_title("", pdf_id, heading="Real Heading") == "Real Heading"
    assert clean_title("", pdf_id, text="Solid State Battery Interfaces\nBody text.") == (
        "Solid State Battery Interfaces"
    )
    # A sentence (ends with a period) isn't taken as a title.
    untitled = clean_title("", pdf_id, text="We report a new result.")
    assert untitled == "Untitled document (inis.iaea.org)"
    assert clean_title("", PDF) == "Global EV Outlook 2025"
    assert clean_title("", "https://www.example.org/") == "example.org"
