import asyncio
import json

import pytest
from pydantic import BaseModel

from adlantis.agents import BaseAgent
from adlantis.config import Settings, load_profile
from adlantis.llm import ModelRouter
from tests.fakes import fake_openai_client, openai_response


class Brief(BaseModel):
    topic: str


class Outline(BaseModel):
    title: str


class OutlineAgent(BaseAgent[Brief, Outline]):
    name = "outline"
    role = "researcher"
    prompt_file = "outline"
    input_schema = Brief
    output_schema = Outline

    @property
    def system_prompt(self) -> str:
        return "Write an outline."


def agent_with(*responses) -> tuple[OutlineAgent, list[dict]]:
    client = fake_openai_client(*responses)
    router = ModelRouter(Settings(), load_profile("budget"), client_factory=lambda _p: client)
    return OutlineAgent(router), client.responses.create.calls


def reply(title: str):
    args = json.dumps({"title": title})
    return openai_response(None, tool_calls=[("c1", "submit_outline", args)])


def test_run_validates_input_and_returns_typed_output() -> None:
    agent, calls = agent_with(reply("Launch"))
    assert agent.run(Brief(topic="coffee")) == Outline(title="Launch")
    assert calls[0]["instructions"] == "Write an outline."
    assert calls[0]["model"] == agent.router.resolve("researcher").model


def test_arun_gives_the_same_result() -> None:
    agent, _ = agent_with(reply("Launch"))
    assert asyncio.run(agent.arun(Brief(topic="coffee"))).title == "Launch"


def test_invalid_input_is_rejected_before_any_model_call() -> None:
    agent, calls = agent_with()
    with pytest.raises(ValueError, match="topic"):
        agent.run({"wrong": "field"})
    assert calls == []
