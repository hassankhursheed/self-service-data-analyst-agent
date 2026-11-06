"""The agent graph: N-01 to N-11 with routing taken only from the transition table.

``Agent`` owns one compiled graph and its checkpointer. ``run`` starts a question;
``resume`` continues a question paused for clarification. The checkpointer is in memory
for now; the PostgreSQL checkpointer replaces it in Step 15.
"""

import uuid
from collections.abc import Callable
from functools import lru_cache
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.agent.checkpoint import checkpoint_serializer
from app.agent.deps import AgentDeps, default_deps
from app.agent.nodes.answer import make_answer_node
from app.agent.nodes.base import NodeFn
from app.agent.nodes.n01_intake import request_intake
from app.agent.nodes.n02_guardrails import input_guardrails
from app.agent.nodes.n03_intent import make_intent_node
from app.agent.nodes.n04_clarification import make_clarification_node
from app.agent.nodes.n05_context import make_context_node
from app.agent.nodes.n06_sql_generation import make_sql_generation_node
from app.agent.nodes.n07_validation import make_validation_node
from app.agent.nodes.n08_execution import make_execution_node
from app.agent.nodes.n09_repair import make_repair_node
from app.agent.nodes.stubs import audit_and_metrics
from app.agent.state import AgentRequest, AgentState
from app.agent.transitions import END as ROUTE_END
from app.agent.transitions import ROUTES, next_node
from app.core.enums import NodeName
from app.core.errors import AppError

Graph = CompiledStateGraph[AgentState, None, AgentState, AgentState]


def build_nodes(deps: AgentDeps) -> dict[NodeName, NodeFn]:
    return {
        NodeName.INTAKE: request_intake,
        NodeName.GUARDRAILS: input_guardrails,
        NodeName.INTENT: make_intent_node(deps),
        NodeName.CLARIFICATION: make_clarification_node(),
        NodeName.CONTEXT: make_context_node(deps),
        NodeName.SQL_GENERATION: make_sql_generation_node(deps),
        NodeName.VALIDATION: make_validation_node(deps),
        NodeName.EXECUTION: make_execution_node(deps),
        NodeName.REPAIR: make_repair_node(deps),
        NodeName.ANSWER: make_answer_node(deps),
        NodeName.AUDIT: audit_and_metrics,
    }


def _router(node: NodeName) -> Callable[[AgentState], str]:
    def route(state: AgentState) -> str:
        target = next_node(node, state.status)
        return END if target == ROUTE_END else target

    route.__name__ = f"route_after_{node.value.replace('-', '_')}"
    return route


def build_graph(deps: AgentDeps, checkpointer: BaseCheckpointSaver[Any] | None = None) -> Graph:
    nodes = build_nodes(deps)
    builder = StateGraph(AgentState)
    for name, fn in nodes.items():
        builder.add_node(name.value, cast(Any, fn))
    builder.add_edge(START, NodeName.INTAKE.value)
    for name in nodes:
        if name is NodeName.AUDIT:
            builder.add_edge(name.value, END)
            continue
        targets = sorted(set(ROUTES[name].values()))
        builder.add_conditional_edges(name.value, _router(name), {t: t for t in targets})
    return builder.compile(checkpointer=checkpointer)


class Agent:
    """One graph plus its checkpointer; safe to reuse for many questions."""

    def __init__(
        self,
        deps: AgentDeps | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
    ) -> None:
        self.deps = deps or default_deps()
        self.graph = build_graph(
            self.deps, checkpointer or InMemorySaver(serde=checkpoint_serializer())
        )

    @staticmethod
    def _config(thread_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": thread_id}}

    async def run(self, request: AgentRequest, *, thread_id: str | None = None) -> AgentState:
        """Run a new question until it finishes or pauses for clarification."""
        thread_id = thread_id or str(uuid.uuid4())
        initial = AgentState(
            request=request,
            thread_id=thread_id,
            graph_version=self.deps.agent_config.graph_version,
            prompt_versions=dict(self.deps.llm_config.prompts),
        )
        await self.graph.ainvoke(initial, self._config(thread_id))
        return await self.state(thread_id)

    async def resume(self, thread_id: str, reply: str) -> AgentState:
        """Continue a paused question with the user's clarification reply."""
        current = await self.state(thread_id)
        if not current.awaiting_reply:
            raise AppError(f"thread {thread_id} is not waiting for a clarification")
        await self.graph.ainvoke(Command(resume=reply), self._config(thread_id))
        return await self.state(thread_id)

    async def state(self, thread_id: str) -> AgentState:
        snapshot = await self.graph.aget_state(self._config(thread_id))
        if not snapshot.values:
            raise AppError(f"unknown thread {thread_id}")
        values = snapshot.values
        state = values if isinstance(values, AgentState) else AgentState.model_validate(values)
        return state.model_copy(update={"awaiting_reply": bool(snapshot.interrupts)})


@lru_cache
def get_agent() -> Agent:
    return Agent()


async def run_agent(request: AgentRequest) -> AgentState:
    """Run one question with the default agent."""
    return await get_agent().run(request)
