import pytest

from adlantis.orchestrator.revision import MAX_EDIT_CHARS, apply_edits
from adlantis.schemas import AssetEdit, RevisionPlan
from tests.agents.copy_helpers import asset

ALLOWED = frozenset({"F-001", "F-003"})
TEXT = "Roasted within 48 hours of shipping. The best coffee in town."


def edit(**changes: object) -> AssetEdit:
    values = {"issue_id": "I1", "field": "body", "find": "The best coffee in town.", "replace": ""}
    return AssetEdit.model_validate({**values, **changes})


def run(*edits: AssetEdit, copy=None):
    copy = copy or asset(TEXT, (("Roasted within 48 hours of shipping.", ("F-001",)),))
    return apply_edits(copy, RevisionPlan(edits=list(edits)), {"I1", "I2"}, ALLOWED)


def test_edit_replaces_only_the_named_passage() -> None:
    result = run(edit(replace="Fresh from the roaster."))
    assert result.asset.fields["body"] == (
        "Roasted within 48 hours of shipping. Fresh from the roaster."
    )
    assert result.asset.fields["subject"] == "Harvest news"
    assert result.applied == 1


def test_original_asset_is_not_changed() -> None:
    copy = asset(TEXT)
    run(edit(), copy=copy)
    assert copy.fields["body"] == TEXT


def test_new_statement_gets_a_citation() -> None:
    result = run(edit(replace="Notes of cocoa.", references=["F-003"]))
    assert result.asset.citations[-1].text == "Notes of cocoa."
    assert result.asset.references == ["F-001", "F-003"]


def test_citation_of_removed_text_is_dropped() -> None:
    result = run(edit(find="Roasted within 48 hours of shipping.", replace="Fresh."))
    assert result.asset.citations == []
    assert result.asset.references == []


def test_several_edits_apply_in_order() -> None:
    result = run(edit(), edit(issue_id="I2", find="Roasted", replace="Packed"))
    assert result.applied == 2
    assert result.asset.fields["body"].startswith("Packed within")


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"issue_id": "I9"}, "open issue"),
        ({"field": "footer"}, "unknown field"),
        ({"find": ""}, "nothing to replace"),
        ({"find": "Not in the copy."}, "exactly one passage"),
        ({"find": "o"}, "exactly one passage"),
        ({"references": ["F-999"]}, "unusable source"),
    ],
)
def test_unsafe_edit_is_refused(changes: dict, reason: str) -> None:
    result = run(edit(**changes))
    assert (result.applied, result.asset.fields["body"]) == (0, TEXT)
    assert reason in result.refused[0]


def test_edit_at_the_size_limit_is_allowed() -> None:
    long = "a" * MAX_EDIT_CHARS
    assert run(edit(find=long, replace="b"), copy=asset(f"{long} tail")).applied == 1


def test_edit_over_the_size_limit_is_refused() -> None:
    long = "a" * (MAX_EDIT_CHARS + 1)
    result = run(edit(find=long, replace="b"), copy=asset(f"{long} tail"))
    assert "too large" in result.refused[0]


def test_edit_cannot_empty_a_field() -> None:
    result = run(edit(find="Solo text.", replace="  "), copy=asset("Solo text."))
    assert "empty" in result.refused[0]


def test_refused_edit_does_not_stop_a_good_one() -> None:
    result = run(edit(issue_id="I9"), edit(issue_id="I2"))
    assert result.applied == 1
    assert len(result.refused) == 1
