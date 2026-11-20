from adlantis.schemas import IssueLedger, IssueReport, IssueVerdict


def report(asset: str = "email-1", quote: str = "Best coffee in town") -> IssueReport:
    return IssueReport(
        asset_id=asset, kind="prohibited_claim", quote=quote, problem="Superlative", fix="Remove it"
    )


def verdict(issue_id: str, status: str) -> IssueVerdict:
    return IssueVerdict(issue_id=issue_id, status=status)


def test_new_issues_get_stable_ids_and_block() -> None:
    ledger = IssueLedger()
    summary = ledger.apply([report(), report("ad-1")], [], 1)
    assert summary.added == ["I1", "I2"]
    assert [i.id for i in ledger.active()] == ["I1", "I2"]
    assert [i.id for i in ledger.active("ad-1")] == ["I2"]
    assert all(i.blocking for i in ledger.issues)


def test_lifecycle_open_resolved_regressed() -> None:
    ledger = IssueLedger()
    ledger.apply([report()], [], 1)
    ledger.apply([], [verdict("I1", "resolved")], 2)
    issue = ledger.get("I1")
    assert (issue.status, issue.round_resolved, issue.blocking) == ("resolved", 2, False)
    assert ledger.resolved() == [issue]

    summary = ledger.apply([], [verdict("I1", "regressed")], 3)
    assert summary.regressed == ["I1"]
    assert (issue.status, issue.round_resolved, issue.blocking) == ("regressed", None, True)
    assert issue.history == ["r1: raised", "r2: resolved", "r3: regressed"]


def test_resolved_problem_reported_again_regresses_instead_of_duplicating() -> None:
    ledger = IssueLedger()
    ledger.apply([report()], [], 1)
    ledger.apply([], [verdict("I1", "resolved")], 2)
    summary = ledger.apply([report(quote="  BEST coffee   in town ")], [], 3)
    assert summary.added == []
    assert summary.regressed == ["I1"]
    assert len(ledger.issues) == 1
    assert ledger.get("I1").status == "regressed"


def test_open_problem_reported_again_is_not_duplicated() -> None:
    ledger = IssueLedger()
    ledger.apply([report()], [], 1)
    summary = ledger.apply([report()], [], 2)
    assert (summary.added, summary.still_open) == ([], ["I1"])
    assert len(ledger.issues) == 1


def test_same_quote_in_another_asset_is_a_separate_issue() -> None:
    ledger = IssueLedger()
    assert ledger.apply([report("a"), report("b")], [], 1).added == ["I1", "I2"]


def test_issue_without_a_verdict_is_never_silently_resolved() -> None:
    ledger = IssueLedger()
    ledger.apply([report("a"), report("b")], [], 1)
    summary = ledger.apply([], [verdict("I1", "resolved")], 2)
    assert ledger.get("I2").status == "open"
    assert summary.unverified == ["I2"]


def test_invalid_transitions_and_unknown_ids_change_nothing() -> None:
    ledger = IssueLedger()
    ledger.apply([report()], [], 1)
    summary = ledger.apply([], [verdict("I1", "regressed"), verdict("I9", "resolved")], 2)
    assert ledger.get("I1").status == "open"
    assert ledger.get("I1").history == ["r1: raised"]
    assert (summary.regressed, summary.resolved) == ([], [])
