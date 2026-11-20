"""The revise loop with scripted agents, so each path can be forced."""

from __future__ import annotations

from adlantis.llm.types import LLMError
from adlantis.orchestrator.review_loop import ReviewContext, ReviewLoop, blocking_reports
from adlantis.schemas import (
    AssetEdit,
    CampaignAsset,
    CheckedClaim,
    ClaimCheckResult,
    RevisionPlan,
    RevisionRequest,
    RuleViolation,
)
from tests.agents.copy_helpers import asset
from tests.rules.helpers import SHEET, TODAY, brand

BAD = "the best coffee"
WORSE = "the greatest coffee"
CONTEXT = ReviewContext(
    brand=brand(),
    facts=SHEET,
    findings=[],
    today=TODAY,
    allowed_references=frozenset({"F-001"}),
)


def blocked(asset_id: str, quote: str, verdict: str = "unsupported") -> CheckedClaim:
    return CheckedClaim(
        id=f"{asset_id}/C1",
        asset_id=asset_id,
        field="body",
        quote=quote,
        claim_type="superlative",
        verdict=verdict,
        reason="No source proves it.",
        fix="Remove it.",
        decided_by="model",
    )


class Checker:
    """Blocks any known bad phrase found in the copy."""

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.seen: list[str] = []
        self.fail_on_call = fail_on_call

    def run(self, data: CampaignAsset) -> ClaimCheckResult:
        self.seen.append(data.fields["body"])
        if self.fail_on_call == len(self.seen):
            raise LLMError("provider failed")
        body = data.fields["body"]
        claims = [blocked(data.asset_id, q) for q in (BAD, WORSE, "bad two") if q in body]
        return ClaimCheckResult(asset_id=data.asset_id, claims=claims)


class Reviser:
    """Applies scripted replacements, one list of (find, replace) per round."""

    def __init__(self, *rounds: list[tuple[str, str]]) -> None:
        self.rounds = list(rounds)
        self.requests: list[RevisionRequest] = []

    def revise(self, data: RevisionRequest) -> RevisionPlan:
        self.requests.append(data)
        script = self.rounds.pop(0) if self.rounds else []
        issue = data.issues[0].id
        edits = [
            AssetEdit(issue_id=issue, field="body", find=find, replace=replace)
            for find, replace in script
        ]
        return RevisionPlan(edits=edits)


class BrokenReviser:
    def revise(self, data: RevisionRequest) -> RevisionPlan:
        raise LLMError("provider failed")


def review(*assets: CampaignAsset, checker=None, reviser=None, **kwargs):
    checker = checker or Checker()
    loop = ReviewLoop(checker, reviser or Reviser(), CONTEXT, **kwargs)
    return loop.review(list(assets)), checker


def bad_asset(text: str = f"Try {BAD} today.", asset_id: str = "email-1") -> CampaignAsset:
    return asset(text, (), asset_id)


def test_clean_asset_ships_without_revision() -> None:
    outcome, checker = review(asset("Slow mornings.", ()))
    assert [a.asset.asset_id for a in outcome.assets] == ["email-1"]
    assert (outcome.assets[0].revisions, outcome.gaps, len(checker.seen)) == (0, [], 1)


def test_fixed_asset_ships_with_its_final_text_and_resolved_issue() -> None:
    outcome, _ = review(bad_asset(), reviser=Reviser([(BAD, "our new harvest")]))
    item = outcome.assets[0]
    assert item.asset.fields["body"] == "Try our new harvest today."
    assert item.revisions == 1
    assert outcome.ledger.issues[0].status == "resolved"
    assert outcome.ledger.active() == []


def test_asset_that_never_passes_is_removed_and_listed_as_a_gap() -> None:
    reviser = Reviser([("Try", "Taste")], [("Taste", "Sample")])
    outcome, _ = review(bad_asset(), reviser=reviser)
    assert outcome.assets == []
    gap = outcome.gaps[0]
    assert (gap.asset_id, gap.channel, gap.issue_ids) == ("email-1", "email", ["I1"])


def test_gap_does_not_carry_the_failing_copy() -> None:
    outcome, _ = review(bad_asset())
    assert "Try" not in outcome.gaps[0].model_dump_json()


def test_at_most_two_revision_rounds_run() -> None:
    reviser = Reviser([("Try", "A")], [("A", "B")], [("B", "C")])
    outcome, checker = review(bad_asset(), reviser=reviser)
    assert len(reviser.requests) == 2
    assert len(checker.seen) == 3
    assert outcome.assets == []


def test_asset_fixed_in_the_second_round_ships() -> None:
    reviser = Reviser([("Try", "Taste")], [(BAD, "our harvest")])
    outcome, _ = review(bad_asset(), reviser=reviser)
    assert outcome.assets[0].revisions == 2


def test_round_limit_can_be_lowered() -> None:
    reviser = Reviser([("Try", "A")], [("A", "B")])
    review(bad_asset(), reviser=reviser, max_rounds=1)
    assert len(reviser.requests) == 1


def test_worse_revision_is_discarded_and_work_resumes_from_the_best_version() -> None:
    original = f"Try {BAD} today."
    reviser = Reviser([("Try", f"Try bad two and {WORSE}, plus")], [(BAD, "our harvest")])
    outcome, _ = review(bad_asset(original), reviser=reviser)
    assert reviser.requests[1].asset.fields["body"] == original
    assert outcome.assets[0].asset.fields["body"] == "Try our harvest today."


def test_only_issues_on_the_best_version_are_sent_for_revision() -> None:
    reviser = Reviser([("Try", f"Try bad two and {WORSE}, plus")], [("today", "now")])
    review(bad_asset(), reviser=reviser)
    assert [issue.quote for issue in reviser.requests[1].issues] == [BAD]


def test_reintroduced_problem_is_marked_regressed() -> None:
    first = f"Try {BAD} today."
    reviser = Reviser([(BAD, "our harvest and bad two")], [("bad two", BAD)])
    outcome, _ = review(bad_asset(first), reviser=reviser)
    statuses = {issue.quote: issue.status for issue in outcome.ledger.issues}
    assert statuses == {BAD: "regressed", "bad two": "resolved"}
    assert outcome.gaps[0].issue_ids == ["I1"]


def test_problem_that_persists_stays_open() -> None:
    reviser = Reviser([("Try", "Taste")], [("Taste", "Sample")])
    outcome, _ = review(bad_asset(), reviser=reviser)
    assert outcome.ledger.get("I1").status == "open"
    assert outcome.ledger.rounds[1].still_open == ["I1"]


def test_discarded_version_does_not_resolve_issues_on_the_kept_version() -> None:
    original = f"Try {BAD} today."
    reviser = Reviser([(BAD, f"bad two and {WORSE}")], [("today", "now")])
    outcome, _ = review(bad_asset(original), reviser=reviser)
    assert reviser.requests[1].asset.fields["body"] == original
    assert [issue.quote for issue in reviser.requests[1].issues] == [BAD]
    assert outcome.ledger.get("I1").status != "resolved"


def test_equally_good_revision_becomes_the_base_for_the_next_round() -> None:
    reviser = Reviser([("Try", "Taste")], [("Taste", "Sample")])
    review(bad_asset(), reviser=reviser)
    assert reviser.requests[1].asset.fields["body"].startswith("Taste")


def test_gap_lists_only_issues_on_the_kept_version() -> None:
    reviser = Reviser([(BAD, f"bad two and {WORSE}")], [("not there", "x")])
    outcome, _ = review(bad_asset(), reviser=reviser)
    assert outcome.gaps[0].issue_ids == ["I1"]


def test_revision_with_no_usable_edit_stops_early() -> None:
    reviser = Reviser([("not in the copy", "x")])
    outcome, checker = review(bad_asset(), reviser=reviser)
    assert len(checker.seen) == 1
    assert len(reviser.requests) == 1
    assert outcome.gaps


def test_failed_claim_check_never_ships_the_asset() -> None:
    outcome, _ = review(asset("Slow mornings.", ()), checker=Checker(fail_on_call=1))
    assert outcome.assets == []
    assert "could not finish" in outcome.gaps[0].reason


def test_failed_recheck_never_ships_the_revision() -> None:
    reviser = Reviser([(BAD, "our harvest")])
    outcome, _ = review(bad_asset(), checker=Checker(fail_on_call=2), reviser=reviser)
    assert outcome.assets == []
    assert outcome.gaps


def test_failed_revision_becomes_a_gap() -> None:
    outcome, _ = review(bad_asset(), reviser=BrokenReviser())
    assert outcome.assets == []
    assert outcome.gaps[0].issue_ids == ["I1"]


def test_one_failing_asset_does_not_hold_back_another() -> None:
    outcome, _ = review(bad_asset(asset_id="email-1"), asset("Slow mornings.", (), "email-2"))
    assert [a.asset.asset_id for a in outcome.assets] == ["email-2"]
    assert [g.asset_id for g in outcome.gaps] == ["email-1"]


def test_ledger_records_each_round() -> None:
    outcome, _ = review(bad_asset(), reviser=Reviser([(BAD, "our harvest")]))
    assert [r.round for r in outcome.ledger.rounds] == [1, 2]
    assert outcome.ledger.rounds[0].added == ["I1"]
    assert outcome.ledger.rounds[1].resolved == ["I1"]


def test_warnings_ship_with_the_asset() -> None:
    warning = RuleViolation(
        rule="channel_limit", severity="warning", asset_id="email-1", message="Long.", fix="Trim."
    )

    class Warns(Checker):
        def run(self, data: CampaignAsset) -> ClaimCheckResult:
            return ClaimCheckResult(asset_id=data.asset_id, warnings=[warning])

    outcome, _ = review(asset("Slow mornings.", ()), checker=Warns())
    assert outcome.assets[0].warnings == [warning]


def test_reports_name_the_kind_of_problem() -> None:
    result = ClaimCheckResult(
        asset_id="a",
        claims=[blocked("a", "one", "prohibited"), blocked("a", "two")],
        rule_errors=[
            RuleViolation(rule="channel_limit", asset_id="a", message="Long.", fix="Trim.")
        ],
    )
    assert [r.kind for r in blocking_reports(result)] == [
        "prohibited_claim",
        "unsupported_claim",
        "rule_violation",
    ]


def test_duplicate_problems_become_one_report() -> None:
    twin = blocked("a", "ONE ").model_copy(update={"id": "a/C2"})
    result = ClaimCheckResult(asset_id="a", claims=[blocked("a", "one"), twin])
    assert len(blocking_reports(result)) == 1
