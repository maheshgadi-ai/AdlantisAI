import pytest

from adlantis.rules import check_asset, count_length, load_channel_limits
from adlantis.schemas import AssetCopy, FieldLimit
from adlantis.schemas.channels import Channel
from tests.rules.helpers import context

RULE = "channel_limit"
LIMITS = load_channel_limits().channels
EVERY_FIELD = [(c, f, spec.max_chars) for c, fields in LIMITS.items() for f, spec in fields.items()]


def hits(channel: str, field: str, text: str) -> list:
    asset = AssetCopy(asset_id="a1", channel=channel, fields={field: text})
    return check_asset(asset, context()).for_rule(RULE)


def test_every_channel_has_limits() -> None:
    assert set(LIMITS) == set(Channel.__args__)


@pytest.mark.parametrize(("channel", "field", "limit"), EVERY_FIELD)
def test_text_at_the_limit_is_not_blocked(channel: str, field: str, limit: int) -> None:
    assert all(v.severity == "warning" for v in hits(channel, field, "a" * limit))


@pytest.mark.parametrize(("channel", "field", "limit"), EVERY_FIELD)
def test_one_character_over_the_limit_is_caught(channel: str, field: str, limit: int) -> None:
    found = hits(channel, field, "a" * (limit + 1))
    assert [v.severity for v in found] == [LIMITS[channel][field].severity]


@pytest.mark.parametrize(
    ("channel", "field", "limit"),
    [("search_ad", "headline", 30), ("search_ad", "description", 90), ("x", "post", 280)],
)
def test_documented_platform_limits(channel: str, field: str, limit: int) -> None:
    assert LIMITS[channel][field].max_chars == limit
    assert LIMITS[channel][field].source.type == "platform"
    assert LIMITS[channel][field].severity == "error"


def test_unknown_field_is_rejected() -> None:
    assert "no field named" in hits("x", "headline", "Short.")[0].message


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hello", 5),
        ("café", 4),
        ("cafe" + chr(0x0301), 4),
        ("日本", 4),
        ("\U0001f600", 2),
        ("\U0001f44d\U0001f3fd", 2),
        ("\U0001f468‍\U0001f469‍\U0001f467", 2),
        ("\U0001f1fa\U0001f1f8", 2),
        ("https://example.org/a/very/long/path/that/keeps/going", 23),
        ("Go https://example.org now", 30),
    ],
)
def test_x_weighted_counting(text: str, expected: int) -> None:
    assert count_length(text, "x_weighted") == expected


def test_double_width_characters_count_twice_for_search_ads() -> None:
    assert count_length("日本", "double_width") == 4
    assert hits("search_ad", "headline", "日" * 15) == []
    assert len(hits("search_ad", "headline", "日" * 16)) == 1


def test_plain_counting_treats_combined_accents_as_one() -> None:
    assert count_length("cafe" + chr(0x0301), "characters") == 4


def test_x_post_of_short_text_with_a_long_url_fits() -> None:
    assert hits("x", "post", "Read it: https://example.org/" + "a" * 400) == []


BLOCKING = {("search_ad", "headline"), ("search_ad", "description"), ("x", "post")}
THIRD_PARTY_PLATFORM = {("instagram", "caption"), ("linkedin", "post")}
TRUNCATION = {("meta_ad", "primary_text"), ("meta_ad", "headline")}


@pytest.mark.parametrize(("channel", "field"), sorted(BLOCKING))
def test_first_party_platform_limits_block(channel: str, field: str) -> None:
    limit = LIMITS[channel][field]
    assert (limit.severity, limit.source.type, limit.source.third_party) == (
        "error",
        "platform",
        False,
    )
    assert limit.source.reference.startswith("https://")


@pytest.mark.parametrize(("channel", "field"), sorted(THIRD_PARTY_PLATFORM))
def test_third_party_platform_caps_block_and_are_marked(channel: str, field: str) -> None:
    limit = LIMITS[channel][field]
    assert (limit.severity, limit.source.type, limit.source.third_party) == (
        "error",
        "platform",
        True,
    )


@pytest.mark.parametrize(("channel", "field"), sorted(TRUNCATION))
def test_truncation_guidelines_warn_and_are_marked_third_party(channel: str, field: str) -> None:
    limit = LIMITS[channel][field]
    assert (limit.severity, limit.source.type, limit.source.third_party) == (
        "warning",
        "guideline",
        True,
    )


@pytest.mark.parametrize("channel", ["email", "landing_page"])
def test_editorial_limits_warn(channel: str) -> None:
    for limit in LIMITS[channel].values():
        assert (limit.severity, limit.source.type, limit.source.third_party) == (
            "warning",
            "editorial",
            False,
        )


def report_for(channel: str, field: str, text: str):
    return check_asset(AssetCopy(asset_id="a", channel=channel, fields={field: text}), context())


def test_warning_is_reported_but_does_not_block() -> None:
    report = report_for("meta_ad", "headline", "a" * 41)
    assert report.passed
    assert [v.rule for v in report.warnings] == ["channel_limit"]
    assert report.errors == []


def test_error_blocks() -> None:
    report = report_for("x", "post", "a" * 281)
    assert not report.passed
    assert [v.severity for v in report.errors] == ["error"]


def test_unknown_field_blocks_even_on_a_warning_channel() -> None:
    assert not report_for("email", "footer", "Hello").passed


def test_warning_does_not_hide_a_content_violation() -> None:
    assert not report_for("meta_ad", "headline", "Reduces anxiety " + "a" * 40).passed


def test_writing_targets_include_warning_limits() -> None:
    limits = load_channel_limits()
    assert limits.writing_targets("instagram") == {"caption": 125}
    assert limits.writing_targets("linkedin") == {"post": 140}
    assert limits.writing_targets("meta_ad") == {"primary_text": 125, "headline": 40}
    assert limits.writing_targets("search_ad") == {"headline": 30, "description": 90}


@pytest.mark.parametrize(
    "bad",
    [
        {"severity": "warning", "source": {"type": "platform", "third_party": False}},
        {"severity": "error", "source": {"type": "guideline", "third_party": True}},
        {"severity": "error", "source": {"type": "editorial", "third_party": False}},
        {"severity": "warning", "source": {"type": "editorial", "third_party": True}},
    ],
)
def test_inconsistent_limit_config_is_rejected(bad: dict) -> None:
    source = {**bad["source"], "reference": "note"}
    with pytest.raises(ValueError, match=r"platform limits|editorial limit"):
        FieldLimit(max_chars=10, severity=bad["severity"], source=source)


FOLDS = [("instagram", "caption", 125, 2200), ("linkedin", "post", 140, 3000)]


@pytest.mark.parametrize(("channel", "field", "fold", "cap"), FOLDS)
def test_fold_and_cap_are_both_marked_third_party(
    channel: str, field: str, fold: int, cap: int
) -> None:
    limit = LIMITS[channel][field]
    assert (limit.max_chars, limit.severity, limit.source.third_party) == (cap, "error", True)
    point = limit.truncation
    assert (point.max_chars, point.severity) == (fold, "warning")
    assert (point.source.type, point.source.third_party) == ("guideline", True)


@pytest.mark.parametrize(("channel", "field", "fold", "cap"), FOLDS)
def test_text_up_to_the_fold_is_clean(channel: str, field: str, fold: int, cap: int) -> None:
    assert hits(channel, field, "a" * fold) == []


@pytest.mark.parametrize(("channel", "field", "fold", "cap"), FOLDS)
def test_text_past_the_fold_warns_without_blocking(
    channel: str, field: str, fold: int, cap: int
) -> None:
    report = report_for(channel, field, "a" * (fold + 1))
    assert report.passed
    assert "see more" in report.warnings[0].message


@pytest.mark.parametrize(("channel", "field", "fold", "cap"), FOLDS)
def test_text_at_the_cap_warns_once_and_past_it_blocks_once(
    channel: str, field: str, fold: int, cap: int
) -> None:
    assert [v.severity for v in hits(channel, field, "a" * cap)] == ["warning"]
    assert [v.severity for v in hits(channel, field, "a" * (cap + 1))] == ["error"]


GUIDE = {"type": "guideline", "third_party": True, "reference": "note"}
PLATFORM = {"type": "platform", "third_party": True, "reference": "note"}


def test_fold_must_be_shorter_than_the_cap() -> None:
    with pytest.raises(ValueError, match="shorter than the hard cap"):
        FieldLimit(
            max_chars=100,
            severity="error",
            source=PLATFORM,
            truncation={"max_chars": 100, "source": GUIDE},
        )


def test_fold_must_come_from_a_guideline() -> None:
    with pytest.raises(ValueError, match="guideline source"):
        FieldLimit(
            max_chars=100,
            severity="error",
            source=PLATFORM,
            truncation={"max_chars": 50, "source": PLATFORM},
        )
