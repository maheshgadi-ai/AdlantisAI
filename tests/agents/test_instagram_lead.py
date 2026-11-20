"""Instagram captions are briefed to state their key message before "see more"."""

from adlantis.agents import Copywriter
from adlantis.prompts import load_prompt
from adlantis.rules.channels import key_message_limit, load_channel_limits
from adlantis.schemas import CopyRequest, RevisionPlan, RevisionRequest
from tests.agents.copy_helpers import PRODUCT, STRATEGY, asset, gpt, router
from tests.rules.helpers import SHEET, TODAY, brand


def brief(channel: str) -> str:
    built, calls = router(openai=(gpt("submit_channel_draft", {"variants": []}),))
    request = CopyRequest(
        brand=brand(),
        product=PRODUCT,
        strategy=STRATEGY,
        facts=SHEET,
        channel=channel,
        today=TODAY,
    )
    Copywriter(built).run(request)
    return str(calls["openai"][0]["input"]).replace("\\", "")


def test_limit_is_the_instagram_see_more_point() -> None:
    caption = load_channel_limits().channels["instagram"]["caption"]
    assert key_message_limit("instagram") == caption.truncation.max_chars == 125


def test_other_channels_have_no_limit() -> None:
    assert key_message_limit("email") is None
    assert key_message_limit("linkedin") is None


def test_instagram_brief_gives_the_limit() -> None:
    assert '"key_message_within_chars": 125' in brief("instagram")


def test_other_briefs_leave_the_limit_empty() -> None:
    assert '"key_message_within_chars": null' in brief("email")


def test_revision_brief_keeps_the_limit() -> None:
    built, calls = router(openai=(gpt("submit_revision_plan", RevisionPlan().model_dump()),))
    copy = asset().model_copy(update={"channel": "instagram", "fields": {"caption": "Fresh."}})
    issue = {
        "asset_id": copy.asset_id,
        "kind": "unsupported_claim",
        "quote": "Fresh.",
        "problem": "No source.",
        "fix": "Remove it.",
        "id": "I1",
        "round_raised": 1,
    }
    request = RevisionRequest(asset=copy, issues=[issue], brand=brand(), facts=SHEET, today=TODAY)
    Copywriter(built).revise(request)
    assert '"key_message_within_chars": 125' in str(calls["openai"][0]["input"]).replace("\\", "")


def test_prompt_puts_the_key_message_first() -> None:
    prompt = load_prompt("copywriter")
    assert prompt.count("key_message_within_chars") == 2
