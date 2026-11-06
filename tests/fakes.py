"""Test doubles shared by unit tests: a scripted chat model and agent dependencies."""

import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from app.agent.config import load_agent_config
from app.agent.deps import AgentDeps
from app.core.llm import LLMClient, load_llm_config
from app.semantic.calendar import load_calendar
from app.semantic.catalog import load_semantic_layer_file

Reply = BaseException | str | dict[str, Any] | Callable[[Sequence[BaseMessage]], str]


class ScriptedModel:
    """Plays back replies in order: dicts become JSON, strings are sent as-is, exceptions
    are raised and callables get the messages. The last reply repeats when the script runs
    out, so a test only needs to script what it cares about."""

    def __init__(self, *script: Reply) -> None:
        self.script = list(script)
        self.calls: list[Sequence[BaseMessage]] = []

    async def ainvoke(self, input: Sequence[BaseMessage], /) -> BaseMessage:
        self.calls.append(input)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(input)
        text = json.dumps(item) if isinstance(item, dict) else item
        return AIMessage(
            content=text,
            usage_metadata={"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
        )


async def _no_sleep(_: float) -> None:
    return None


def fake_deps(model: ScriptedModel) -> AgentDeps:
    llm_config = load_llm_config()
    return AgentDeps(
        llm=LLMClient(model, llm_config, sleep=_no_sleep),
        llm_config=llm_config,
        agent_config=load_agent_config(),
        calendar=load_calendar(),
        semantic=load_semantic_layer_file(),
    )


def intent(**fields: object) -> dict[str, Any]:
    """An intent-analysis reply; defaults describe a clear question."""
    base: dict[str, Any] = {
        "summary": "Total revenue in 2024",
        "metric": "revenue",
        "metric_options": [],
        "time_phrase": "2024",
        "entities": [],
        "grouping": None,
        "top_n": None,
        "missing": [],
        "assumptions": [],
        "clarifying_question": None,
        "options": [],
    }
    base.update(fields)
    return base


CLEAR_INTENT = intent()
