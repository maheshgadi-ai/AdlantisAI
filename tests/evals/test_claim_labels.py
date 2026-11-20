from pathlib import Path

import pytest
from pydantic import ValidationError

from adlantis.evals.claim_labels import load_claim_labels
from adlantis.schemas import ALL_CLAIM_TYPES

LABELS = load_claim_labels().snippets


def test_set_has_about_forty_snippets() -> None:
    assert 40 <= len(LABELS) <= 50


def test_every_claim_type_is_represented() -> None:
    assert {claim.claim_type for s in LABELS for claim in s.claims} == set(ALL_CLAIM_TYPES)


def test_both_fictional_brands_are_represented() -> None:
    assert {s.brand for s in LABELS} == {"tamsin-hollow-roasters", "kestrune-cycles"}


def test_set_includes_copy_with_no_claims() -> None:
    assert sum(1 for s in LABELS if not s.claims) >= 6


def test_set_includes_copy_with_several_claims() -> None:
    assert sum(1 for s in LABELS if len(s.claims) >= 2) >= 8


@pytest.mark.parametrize("snippet", LABELS, ids=lambda s: s.id)
def test_quotes_are_exact_passages(snippet) -> None:
    assert all(claim.quote in snippet.text for claim in snippet.claims)


def test_quote_outside_the_text_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text(
        "snippets:\n  - {id: CE-001, brand: b, channel: x, text: Hello, "
        "claims: [{quote: Goodbye, claim_type: other}]}\n"
    )
    with pytest.raises(ValidationError, match="quotes not found"):
        load_claim_labels(path)


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    row = "  - {id: CE-001, brand: b, channel: x, text: Hello, claims: []}\n"
    path = tmp_path / "labels.yaml"
    path.write_text("snippets:\n" + row + row)
    with pytest.raises(ValidationError, match="unique"):
        load_claim_labels(path)
