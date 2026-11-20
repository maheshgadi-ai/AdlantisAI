"""The spending cap holds under concurrency and refuses calls before they are sent."""

import threading

import pytest

from adlantis.config import Settings, load_profile
from adlantis.llm import Message, ModelRouter, RunUsage, Usage
from adlantis.llm.budget import BudgetCap, BudgetExceeded
from tests.fakes import fake_openai_client, openai_response


def router(cap: float, *responses):
    client = fake_openai_client(*responses)
    built = ModelRouter(
        Settings(_env_file=None),
        load_profile("budget"),
        client_factory=lambda _provider: client,
        max_cost_usd=cap,
    )
    return built, client.responses.create.calls


def test_cap_must_be_positive() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        BudgetCap(0)


def test_amount_that_exactly_fits_is_allowed() -> None:
    cap = BudgetCap(1.0)
    cap.reserve(1.0)
    cap.release(1.0)


def test_amount_over_the_cap_is_refused() -> None:
    with pytest.raises(BudgetExceeded, match=r"Budget cap of \$1\.00"):
        BudgetCap(1.0).reserve(1.01)


def test_recorded_usage_counts_against_the_cap() -> None:
    usage = RunUsage()
    usage.record(Usage(input_tokens=1, output_tokens=1), 0.9)
    with pytest.raises(BudgetExceeded):
        BudgetCap(1.0, usage).reserve(0.2)


def test_other_charges_count_against_the_cap() -> None:
    cap = BudgetCap(1.0)
    cap.charge(0.9)
    assert (cap.spent_usd, cap.other_usd) == (0.9, 0.9)
    with pytest.raises(BudgetExceeded):
        cap.reserve(0.2)


def test_call_waits_for_a_hold_to_be_released() -> None:
    cap = BudgetCap(1.0)
    cap.reserve(0.8)
    entered = threading.Event()

    def later() -> None:
        cap.reserve(0.8)
        entered.set()

    thread = threading.Thread(target=later, daemon=True)
    thread.start()
    assert not entered.wait(0.05)
    cap.release(0.8)
    assert entered.wait(2)
    thread.join(2)


def test_waiting_call_is_refused_when_the_money_was_really_spent() -> None:
    usage = RunUsage()
    cap = BudgetCap(1.0, usage)
    cap.reserve(0.8)
    errors: list[Exception] = []

    def later() -> None:
        try:
            cap.reserve(0.8)
        except BudgetExceeded as exc:
            errors.append(exc)

    thread = threading.Thread(target=later, daemon=True)
    thread.start()
    usage.record(Usage(input_tokens=1, output_tokens=1), 0.8)
    cap.release(0.8)
    thread.join(2)
    assert len(errors) == 1


def test_concurrent_holds_never_pass_the_cap() -> None:
    cap = BudgetCap(1.0)
    peak: list[float] = []
    lock = threading.Lock()

    def work() -> None:
        cap.reserve(0.4)
        with lock:
            peak.append(cap._held_usd)
        cap.release(0.4)

    threads = [threading.Thread(target=work, daemon=True) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert len(peak) == 12 and max(peak) <= 1.0


def test_provider_refuses_before_anything_is_sent() -> None:
    built, calls = router(0.0001, openai_response())
    with pytest.raises(BudgetExceeded):
        built.for_role("researcher").complete([Message.user("Hello")])
    assert calls == []


def test_provider_sends_when_the_call_fits_and_releases_its_hold() -> None:
    built, calls = router(5.0, openai_response())
    built.for_role("researcher").complete([Message.user("Hello")])
    assert len(calls) == 1
    assert (built.budget._held_usd, built.budget._holds) == (0.0, 0)


def test_hold_is_released_when_the_provider_fails() -> None:
    built, _calls = router(5.0, RuntimeError("down"))
    with pytest.raises(Exception, match="down"):
        built.for_role("researcher").complete([Message.user("Hello")])
    assert built.budget._holds == 0


def test_hold_covers_the_full_output_limit() -> None:
    built, _calls = router(5.0)
    provider = built.for_role("strategist")
    seen: list[float] = []
    provider.budget.reserve = seen.append
    provider._reserve(_request(max_tokens=1000))
    assert seen[0] >= 1000 * provider.pricing.output_per_mtok / 1_000_000


def test_longer_input_holds_more() -> None:
    built, _calls = router(5.0)
    provider = built.for_role("strategist")
    seen: list[float] = []
    provider.budget.reserve = seen.append
    provider._reserve(_request("short"))
    provider._reserve(_request("long " * 500))
    assert seen[1] > seen[0]


def test_unpriced_model_is_refused_under_a_cap() -> None:
    built, calls = router(5.0, openai_response())
    provider = built.for_role("researcher")
    provider.pricing = provider.pricing.model_copy(
        update={"input_per_mtok": 0.0, "output_per_mtok": 0.0}
    )
    with pytest.raises(BudgetExceeded, match="no configured price"):
        provider.complete([Message.user("Hello")])
    assert calls == []


def test_without_a_cap_calls_are_not_limited() -> None:
    client = fake_openai_client(openai_response())
    built = ModelRouter(
        Settings(_env_file=None), load_profile("budget"), client_factory=lambda _p: client
    )
    built.for_role("researcher").complete([Message.user("Hello")])
    assert built.budget is None


def _request(text: str = "Hello", max_tokens: int = 100):
    from adlantis.llm import CompletionRequest

    return CompletionRequest(messages=[Message.user(text)], max_tokens=max_tokens)
