from pydantic import BaseModel

from adlantis.observability import Tracer
from adlantis.tools import BaseTool, ToolError, TransientToolError
from tests.fakes import FakeLangfuse


class EchoArgs(BaseModel):
    text: str


class EchoTool(BaseTool[EchoArgs]):
    """Fails according to a script of exceptions, then echoes its input."""

    name = "echo"
    description = "Echo the text back"
    args_schema = EchoArgs

    def __init__(self, failures: list[Exception] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.failures = list(failures or [])
        self.calls = 0

    def _run(self, args: EchoArgs) -> dict:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return {"echo": args.text}


def make(failures=None, tracer=None) -> tuple[EchoTool, list[float]]:
    sleeps: list[float] = []
    return EchoTool(failures, tracer=tracer, sleep=sleeps.append), sleeps


def test_success() -> None:
    tool, sleeps = make()
    result = tool.run({"text": "hi"})
    assert result.ok
    assert result.data == {"echo": "hi"}
    assert (result.attempts, sleeps) == (1, [])


def test_retries_transient_errors_with_exponential_backoff() -> None:
    tool, sleeps = make([TransientToolError("timeout"), TransientToolError("503")])
    result = tool.run(EchoArgs(text="hi"))
    assert result.ok
    assert result.attempts == 3
    assert sleeps == [0.5, 1.0]


def test_gives_up_after_max_attempts() -> None:
    tool, sleeps = make([TransientToolError("timeout")] * 5)
    result = tool.run({"text": "hi"})
    assert not result.ok
    assert result.error == "timeout"
    assert tool.calls == 3
    assert len(sleeps) == 2


def test_permanent_error_not_retried() -> None:
    tool, sleeps = make([ToolError("404 not found")])
    result = tool.run({"text": "hi"})
    assert not result.ok
    assert (tool.calls, sleeps) == (1, [])


def test_invalid_args_returned_as_error_without_running() -> None:
    tool, _ = make()
    result = tool.run({"txt": "typo"})
    assert not result.ok
    assert "Invalid arguments" in (result.error or "")
    assert tool.calls == 0


def test_parameters_schema_comes_from_args_model() -> None:
    tool, _ = make()
    assert tool.parameters_schema()["properties"]["text"]["type"] == "string"


def test_run_is_traced_as_tool_span() -> None:
    langfuse = FakeLangfuse()
    tool, _ = make([ToolError("bad")], tracer=Tracer(langfuse))
    tool.run({"text": "hi"})
    (span,) = langfuse.observations
    assert span.start_kwargs["name"] == "tool.echo"
    assert span.start_kwargs["as_type"] == "tool"
    assert span.updates[-1]["level"] == "WARNING"
