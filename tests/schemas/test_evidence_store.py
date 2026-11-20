import pytest
from pydantic import ValidationError

from adlantis.schemas import EvidenceStore, SourceRating, canonical_url

RATING = SourceRating(score=0.9, tier="high", label="news", rule="domain:example.org")


def add(store: EvidenceStore, url: str = "https://example.org/a", excerpt: str = "Text", **kw):
    return store.add(url=url, title="Title", excerpt=excerpt, tool="fetch_url", rating=RATING, **kw)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://Example.org/a/", "https://example.org/a"),
        ("https://www.example.org/a", "https://example.org/a"),
        ("https://example.org/a#part", "https://example.org/a"),
        ("https://example.org/a?utm_source=x", "https://example.org/a"),
        ("https://example.org/a?UTM_medium=x&gclid=1", "https://example.org/a"),
        ("https://example.org/a?fbclid=1&msclkid=2", "https://example.org/a"),
        ("https://example.org/a?mc_cid=1&mc_eid=2&ref_src=3", "https://example.org/a"),
        ("https://example.org/a?page=2", "https://example.org/a?page=2"),
        ("https://example.org:8443/a", "https://example.org:8443/a"),
    ],
)
def test_canonical_url(url: str, expected: str) -> None:
    assert canonical_url(url) == expected


def test_ids_are_sequential() -> None:
    store = EvidenceStore()
    assert [add(store, f"https://example.org/{n}").id for n in range(3)] == ["E-1", "E-2", "E-3"]


def test_same_page_and_text_keeps_its_id() -> None:
    store = EvidenceStore()
    first = add(store, "https://example.org/a")
    again = add(store, "https://www.example.org/a/?utm_source=mail")
    assert again.id == first.id
    assert len(store.records) == 1


def test_changed_text_gets_a_new_id_and_the_old_record_survives() -> None:
    store = EvidenceStore()
    first = add(store, excerpt="Original wording.")
    changed = add(store, excerpt="Edited wording.")
    assert changed.id == "E-2"
    assert store.get(first.id).excerpt == "Original wording."


def test_records_cannot_be_edited() -> None:
    record = add(EvidenceStore())
    with pytest.raises(ValidationError):
        record.excerpt = "Tampered"


def test_ids_survive_a_save_and_reload() -> None:
    store = EvidenceStore()
    add(store, "https://example.org/1")
    add(store, "https://example.org/2")
    reloaded = EvidenceStore.model_validate_json(store.model_dump_json())
    assert reloaded == store
    assert add(reloaded, "https://example.org/3").id == "E-3"


def test_reloaded_store_with_gaps_in_ids_is_rejected() -> None:
    store = EvidenceStore()
    add(store)
    data = store.model_dump(mode="json")
    data["records"][0]["id"] = "E-7"
    with pytest.raises(ValidationError, match="in order"):
        EvidenceStore.model_validate(data)


def test_flagged_source_is_quarantined_and_not_citable() -> None:
    store = EvidenceStore()
    good = add(store, "https://example.org/good")
    bad = add(store, "https://example.org/bad", injection_signals=("override",))
    assert (good.status, bad.status) == ("usable", "quarantined")
    assert store.usable() == [good]
    assert store.quarantined() == [bad]
    assert store.usable_ids() == {"E-1"}
