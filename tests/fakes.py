"""Test doubles shared by tests: a scripted chat model, a fake executor and agent deps."""

import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from app.agent.config import load_agent_config
from app.agent.deps import AgentDeps, Executor
from app.core.context import UserContext
from app.core.llm import LLMClient, load_llm_config
from app.db.analytics import QueryResult
from app.safety.sql_policy import load_sql_policy
from app.semantic.calendar import load_calendar
from app.semantic.catalog import load_semantic_layer_file
from app.semantic.models import SemanticLayer

Reply = BaseException | str | dict[str, Any] | Callable[[Sequence[BaseMessage]], str]

# First words of each prompt, used to route a call to the right script.
_ROUTES = {
    "intent": "You analyse business questions",
    "sql": "You write PostgreSQL queries",
    "repair": "You fix a PostgreSQL query",
    "answer": "You explain query results",
}


def sql_reply(sql: str, tables: list[str], **fields: object) -> dict[str, Any]:
    reply: dict[str, Any] = {
        "sql": sql,
        "tables_used": tables,
        "metrics_used": [],
        "date_range": None,
        "assumptions": [],
        "confidence": "high",
    }
    reply.update(fields)
    return reply


DEFAULT_SQL = sql_reply("SELECT count(*) AS orders FROM orders", ["orders"])
DEFAULT_ANSWER = {"explanation": "There were 830 orders.", "sql_description": "Counts orders."}


class ScriptedModel:
    """Plays back replies per prompt kind. Positional replies answer the intent prompt;
    ``sql`` and ``repair`` script the other prompts. Dicts become JSON, strings are sent
    as-is, exceptions are raised. The last reply of each script repeats."""

    def __init__(
        self,
        *intent: Reply,
        sql: Sequence[Reply] = (DEFAULT_SQL,),
        repair: Sequence[Reply] = (DEFAULT_SQL,),
        answer: Sequence[Reply] = (DEFAULT_ANSWER,),
    ) -> None:
        self.scripts: dict[str, list[Reply]] = {
            "intent": list(intent),
            "sql": list(sql),
            "repair": list(repair),
            "answer": list(answer),
        }
        self.calls_by_kind: dict[str, list[Sequence[BaseMessage]]] = {k: [] for k in _ROUTES}

    @property
    def calls(self) -> list[Sequence[BaseMessage]]:
        """Calls to the intent prompt (kept for the Step 12 tests)."""
        return self.calls_by_kind["intent"]

    def _kind(self, messages: Sequence[BaseMessage]) -> str:
        text = " ".join(str(m.content) for m in messages[:3])
        for kind, marker in _ROUTES.items():
            if marker in text:
                return kind
        raise AssertionError("unknown prompt sent to the scripted model")

    async def ainvoke(self, input: Sequence[BaseMessage], /) -> BaseMessage:
        kind = self._kind(input)
        self.calls_by_kind[kind].append(input)
        script = self.scripts[kind]
        if not script:
            raise AssertionError(f"no scripted reply for the {kind} prompt")
        item = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(input)
        text = json.dumps(item) if isinstance(item, dict) else item
        return AIMessage(
            content=text,
            usage_metadata={"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
        )


class FakeExecutor:
    """Plays back results or errors for N-08 and records every SQL it was asked to run."""

    def __init__(self, *outcomes: QueryResult | BaseException) -> None:
        self.outcomes = list(outcomes) or [ONE_ROW]
        self.calls: list[tuple[str, UserContext]] = []

    async def __call__(
        self, sql: str, user: UserContext, timeout_ms: int, row_limit: int
    ) -> QueryResult:
        self.calls.append((sql, user))
        item = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(item, BaseException):
            raise item
        return item


ONE_ROW = QueryResult(columns=["orders"], rows=[(830,)], row_count=1, truncated=False)


async def _no_sleep(_: float) -> None:
    return None


def static_semantic(layer: SemanticLayer | None = None) -> Callable[[], Any]:
    layer = layer or load_semantic_layer_file()

    async def load() -> SemanticLayer:
        assert layer is not None
        return layer

    return load


def fake_deps(
    model: ScriptedModel,
    executor: Executor | None = None,
    semantic: SemanticLayer | None = None,
) -> AgentDeps:
    llm_config = load_llm_config()
    return AgentDeps(
        llm=LLMClient(model, llm_config, sleep=_no_sleep),
        llm_config=llm_config,
        agent_config=load_agent_config(),
        calendar=load_calendar(),
        load_semantic=static_semantic(semantic),
        executor=executor or FakeExecutor(),
        sql_policy=load_sql_policy(),
        statement_timeout_ms=5000,
        row_limit=1000,
        sleep=_no_sleep,
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
