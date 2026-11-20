from datetime import date, timedelta

import pytest

from adlantis.rules import RULES, check_asset, check_assets
from adlantis.schemas import AssetCopy, RuleId
from tests.rules.helpers import TODAY, asset, context, fires, report

EXPIRED = "expired_fact"
UNKNOWN = "unknown_reference"


def test_citing_an_expired_fact_is_caught() -> None:
    assert fires(EXPIRED, "A seasonal note.", ("F-008",))


def test_repeating_expired_wording_without_a_citation_is_caught() -> None:
    assert fires(EXPIRED, "Our bags are compostable.")


def test_repeating_expired_wording_in_another_case_is_caught() -> None:
    assert fires(EXPIRED, "OUR BAGS ARE COMPOSTABLE.")


def test_fact_is_valid_on_its_expiry_date() -> None:
    assert not fires(EXPIRED, "A note.", ("F-010",))


def test_fact_expires_the_day_after() -> None:
    assert fires(EXPIRED, "A note.", ("F-010",), context(today=TODAY + timedelta(days=1)))


def test_old_fact_was_valid_before_its_expiry() -> None:
    assert not fires(EXPIRED, "Holiday bundle.", ("F-008",), context(today=date(2026, 1, 31)))


def test_fact_without_expiry_never_expires() -> None:
    assert not fires(EXPIRED, "A note.", ("F-001",), context(today=date(2099, 1, 1)))


def test_expired_fact_that_is_not_used_is_ignored() -> None:
    assert not fires(EXPIRED, "Roasted to order.")


def test_unknown_fact_reference_is_caught() -> None:
    assert fires(UNKNOWN, "A note.", ("F-999",))


@pytest.mark.parametrize("reference", ["fact-1", "F-1", "E-", "E-x"])
def test_malformed_reference_is_caught(reference: str) -> None:
    assert fires(UNKNOWN, "A note.", (reference,))


@pytest.mark.parametrize("reference", ["F-001", "E-12"])
def test_known_fact_and_evidence_references_are_allowed(reference: str) -> None:
    assert not fires(UNKNOWN, "A note.", (reference,))


def test_every_rule_id_has_a_check() -> None:
    assert set(RULES) == set(RuleId.__args__)


def test_clean_copy_passes_every_rule() -> None:
    text = "Roasted within 48 hours of shipping. Notes of red apple and cocoa."
    assert report(text, ("F-001",)).passed


def test_results_are_reproducible_and_ordered() -> None:
    text = "The best miracle. Only $9. Harrowfen is awful. Reduces anxiety."
    first, second = report(text), report(text)
    assert first == second
    starts = [v.start for v in first.violations if v.start is not None]
    assert starts == sorted(starts)


def test_every_field_of_an_asset_is_checked() -> None:
    copy = AssetCopy(
        asset_id="e1",
        channel="email",
        fields={"subject": "A miracle.", "body": "Reduces anxiety."},
    )
    found = {v.field: v.rule for v in check_asset(copy, context()).violations}
    assert found == {"subject": "banned_word", "body": "health_claim"}


def test_violations_name_the_asset_quote_and_fix() -> None:
    violation = report("A miracle.").violations[0]
    assert (violation.asset_id, violation.quote) == ("a1", "miracle")
    assert violation.fix


def test_several_assets_are_reported_together() -> None:
    combined = check_assets([asset("A miracle."), asset("A plain note.")], context())
    assert len(combined.violations) == 1


def test_known_evidence_id_is_allowed_when_the_store_is_given() -> None:
    ctx = context(evidence_ids=frozenset({"E-1"}))
    assert not fires(UNKNOWN, "A note.", ("E-1",), ctx)


def test_evidence_missing_from_the_store_is_caught() -> None:
    ctx = context(evidence_ids=frozenset({"E-1"}))
    assert fires(UNKNOWN, "A note.", ("E-2",), ctx)
