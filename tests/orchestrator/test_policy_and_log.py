"""Retries, timeouts, and the run log."""

import json
import threading
from datetime import UTC, datetime

import pytest

from adlantis.llm import LLMError
from adlantis.llm.budget import BudgetExceeded
from adlantis.orchestrator.policy import (
    DEFAULT_POLICIES,
    AgentPolicy,
    AgentTimeout,
    GuardedChecker,
    GuardedReviser,
    call_with_policy,
)
from adlantis.orchestrator.run_log import MAX_DETAIL_CHARS, RunLog

FAST = AgentPolicy(timeout_seconds=5, retries=1)


class Flaky:
    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    def __call__(self, data: str) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return data


def test_success_runs_once() -> None:
    work = Flaky()
    assert (call_with_policy(work, "ok", FAST), work.calls) == ("ok", 1)


def test_model_failure_is_retried() -> None:
    work = Flaky(LLMError("busy"))
    assert (call_with_policy(work, "ok", FAST), work.calls) == ("ok", 2)


def test_failure_after_the_last_retry_is_raised() -> None:
    work = Flaky(LLMError("one"), LLMError("two"))
    with pytest.raises(LLMError, match="two"):
        call_with_policy(work, "ok", FAST)
    assert work.calls == 2


def test_budget_stop_is_never_retried() -> None:
    work = Flaky(BudgetExceeded("cap"))
    with pytest.raises(BudgetExceeded):
        call_with_policy(work, "ok", FAST)
    assert work.calls == 1


def test_programming_errors_are_not_retried() -> None:
    work = Flaky(KeyError("bug"))
    with pytest.raises(KeyError):
        call_with_policy(work, "ok", FAST)
    assert work.calls == 1


def test_slow_agent_times_out() -> None:
    release = threading.Event()
    policy = AgentPolicy(timeout_seconds=0.01, retries=0)
    with pytest.raises(AgentTimeout, match="strategist did not finish"):
        call_with_policy(lambda _data: release.wait(5), "ok", policy, "strategist")
    release.set()


def test_research_is_never_repeated() -> None:
    assert DEFAULT_POLICIES["researcher"].retries == 0


def test_guards_apply_the_policy() -> None:
    class Agent:
        def __init__(self) -> None:
            self.run = Flaky(LLMError("busy"))
            self.revise = Flaky(LLMError("busy"))

    agent = Agent()
    assert GuardedChecker(agent, FAST).run("a") == "a"
    assert GuardedReviser(agent, FAST).revise("b") == "b"


NOW = datetime(2026, 11, 18, tzinfo=UTC)


def test_events_are_written_as_json_lines(tmp_path) -> None:
    path = tmp_path / "run_log.jsonl"
    log = RunLog(path, clock=lambda: NOW, spent=lambda: 0.25)
    log.record("research", "started")
    log.record("research", "finished", "3 findings")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["status"] for row in rows] == ["started", "finished"]
    assert (rows[1]["detail"], rows[1]["spent_usd"]) == ("3 findings", 0.25)


@pytest.mark.parametrize("key", ["sk-abcdefghijkl", "tvly-abcdefghijkl", "lf-abcdefghijkl"])
def test_anything_shaped_like_a_key_is_removed(key: str) -> None:
    assert RunLog().record("run", "failed", f"auth failed for {key}").detail == (
        "auth failed for [removed]"
    )


def test_long_details_are_shortened() -> None:
    assert len(RunLog().record("run", "failed", "x" * 900).detail) == MAX_DETAIL_CHARS


def test_listener_sees_each_event() -> None:
    seen = []
    RunLog(on_event=seen.append).record("run", "started")
    assert seen[0].stage == "run"


def test_concurrent_events_stay_whole(tmp_path) -> None:
    path = tmp_path / "run_log.jsonl"
    log = RunLog(path)
    threads = [
        threading.Thread(target=log.record, args=(f"copy:{n}", "started")) for n in range(30)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len([json.loads(line) for line in path.read_text().splitlines()]) == 30
