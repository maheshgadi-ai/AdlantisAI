"""Citations follow their statements through targeted edits."""

from adlantis.orchestrator.revision import apply_edits
from adlantis.schemas import AssetEdit, RevisionPlan
from tests.agents.copy_helpers import asset

ALLOWED = frozenset({"F-001", "F-002", "F-003"})
ORIGIN = "Finca Monte Tamsal, Huila, Colombia: washed Caturra (fruit removed before drying)."


def edit(find: str, replace: str = "", references: tuple[str, ...] = ()) -> AssetEdit:
    return AssetEdit(
        issue_id="I1", field="body", find=find, replace=replace, references=list(references)
    )


def run(text: str, cited: str, *edits: AssetEdit, required: dict | None = None):
    copy = asset(text, ((cited, ("F-002",)),))
    plan = RevisionPlan(edits=list(edits))
    return apply_edits(copy, plan, {"I1"}, ALLOWED, required)


def test_trimming_a_cited_statement_keeps_its_source() -> None:
    result = run(ORIGIN, ORIGIN, edit(" (fruit removed before drying)")).asset
    assert result.fields["body"] == "Finca Monte Tamsal, Huila, Colombia: washed Caturra."
    assert [(c.text, c.references) for c in result.citations] == [
        ("Finca Monte Tamsal, Huila, Colombia: washed Caturra.", ["F-002"])
    ]
    assert result.references == ["F-002"]


def test_rewording_part_of_a_statement_keeps_old_and_new_sources() -> None:
    result = run(ORIGIN, ORIGIN, edit("washed Caturra", "a washed Caturra", ("F-003",))).asset
    carried = next(c for c in result.citations if "a washed Caturra (fruit" in c.text)
    assert carried.references == ["F-002", "F-003"]


def test_replacing_a_whole_statement_does_not_carry_its_source() -> None:
    result = run(f"{ORIGIN} Fresh.", ORIGIN, edit(ORIGIN, "Notes of cocoa.", ("F-003",))).asset
    assert [(c.text, c.references) for c in result.citations] == [("Notes of cocoa.", ["F-003"])]


def test_removing_a_whole_statement_removes_its_citation() -> None:
    result = run(f"{ORIGIN} Fresh.", ORIGIN, edit(f"{ORIGIN} ")).asset
    assert (result.citations, result.references) == ([], [])


def test_edit_overlapping_the_end_of_a_statement_keeps_the_rest() -> None:
    text = "Washed Caturra from Huila. Fruit removed early."
    result = run(text, "Washed Caturra from Huila.", edit(" Huila. Fruit removed early.")).asset
    assert [c.text for c in result.citations] == ["Washed Caturra from"]


def test_edit_overlapping_the_start_of_a_statement_keeps_the_rest() -> None:
    text = "Fresh today. Washed Caturra from Huila."
    result = run(text, "Washed Caturra from Huila.", edit("Fresh today. Washed ")).asset
    assert [c.text for c in result.citations] == ["Caturra from Huila."]


def test_edit_elsewhere_leaves_a_citation_alone() -> None:
    result = run(f"{ORIGIN} Fresh.", ORIGIN, edit(" Fresh.")).asset
    assert [c.text for c in result.citations] == [ORIGIN]


def test_edit_before_a_statement_leaves_its_citation_alone() -> None:
    result = run(f"Fresh. {ORIGIN}", ORIGIN, edit("Fresh. ")).asset
    assert [c.text for c in result.citations] == [ORIGIN]


def test_only_punctuation_left_is_not_a_statement() -> None:
    result = run("Washed. Fresh.", "Washed.", edit("Washed")).asset
    assert result.citations == []


def test_edit_cannot_remove_a_required_name() -> None:
    text = "Hollow Reserve Coffee"
    edits = edit("Hollow Reserve Coffee", "Roasted to order")
    result = run(text, text, edits, required={"body": "Hollow Reserve"})
    assert (result.applied, result.asset.fields["body"]) == (0, text)
    assert result.refused == ["I1: would remove the required product name"]


def test_edit_that_keeps_a_required_name_is_applied() -> None:
    text = "Hollow Reserve Coffee"
    result = run(text, text, edit(" Coffee"), required={"body": "Hollow Reserve"})
    assert result.asset.fields["body"] == "Hollow Reserve"


def test_edit_may_add_to_a_field_that_lacks_the_required_name() -> None:
    result = run("Fresh", "Fresh", edit("Fresh", "Roasted"), required={"body": "Hollow"})
    assert result.applied == 1
