"""Base class for agents: role, prompt file, typed input and output, and tracing."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC
from typing import ClassVar, Generic, TypeVar

from pydantic import BaseModel

from adlantis.llm.router import ModelRouter
from adlantis.llm.types import Message
from adlantis.prompts import load_prompt

logger = logging.getLogger(__name__)

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """One step of the pipeline, backed by the model the router assigns to `role`.

    Subclasses set the class attributes. By default an agent makes one structured
    call: the prompt file as the system message, `render_input()` as the user
    message, and `output_schema` enforced. Override `_run` for anything else.
    """

    name: ClassVar[str]
    role: ClassVar[str]
    prompt_file: ClassVar[str]
    input_schema: ClassVar[type[BaseModel]]
    output_schema: ClassVar[type[BaseModel]]

    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    @property
    def system_prompt(self) -> str:
        """The agent's instructions, from `prompts/<prompt_file>.md`."""
        return load_prompt(self.prompt_file)

    def run(self, data: InputT) -> OutputT:
        """Validate `data`, run the agent inside an `agent` trace span, and return its output."""
        data = self.input_schema.model_validate(data)
        with self.router.tracer.observe(
            f"agent.{self.name}",
            as_type="agent",
            input=data.model_dump(mode="json"),
            metadata={"role": self.role, "prompt": self.prompt_file},
        ) as obs:
            output = self._run(data)
            obs.update(output=output.model_dump(mode="json"))
        logger.info("agent finished", extra={"agent": self.name, "role": self.role})
        return output

    async def arun(self, data: InputT) -> OutputT:
        """Run the agent in a worker thread so independent agents can overlap under asyncio."""
        return await asyncio.to_thread(self.run, data)

    def render_input(self, data: InputT) -> str:
        """The user message for `data`. Defaults to indented JSON."""
        return data.model_dump_json(indent=2)

    def _run(self, data: InputT) -> OutputT:
        messages = [Message.system(self.system_prompt), Message.user(self.render_input(data))]
        llm = self.router.for_role(self.role)
        return llm.structured(messages, self.output_schema, trace_name=f"{self.name}.llm")
