"""The agent graph: N-01 to N-11 with routing taken only from the transition table."""

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes.base import NodeFn
from app.agent.nodes.n01_intake import request_intake
from app.agent.nodes.n02_guardrails import input_guardrails
from app.agent.nodes.stubs import (
    answer_and_visualization,
    audit_and_metrics,
    clarification,
    context_retrieval,
    execution,
    intent_and_ambiguity,
    repair,
    sql_generation,
    sql_validation,
)
from app.agent.state import AgentRequest, AgentState
from app.agent.transitions import END as ROUTE_END
from app.agent.transitions import ROUTES, next_node
from app.core.config import PROJECT_ROOT
from app.core.enums import NodeName
from app.core.llm import get_llm_config

AGENT_CONFIG_FILE = PROJECT_ROOT / "config" / "agent.yaml"

NODES: dict[NodeName, NodeFn] = {
    NodeName.INTAKE: request_intake,
    NodeName.GUARDRAILS: input_guardrails,
    NodeName.INTENT: intent_and_ambiguity,
    NodeName.CLARIFICATION: clarification,
    NodeName.CONTEXT: context_retrieval,
    NodeName.SQL_GENERATION: sql_generation,
    NodeName.VALIDATION: sql_validation,
    NodeName.EXECUTION: execution,
    NodeName.REPAIR: repair,
    NodeName.ANSWER: answer_and_visualization,
    NodeName.AUDIT: audit_and_metrics,
}


def graph_version(path: Path = AGENT_CONFIG_FILE) -> str:
    data = yaml.safe_load(path.read_text("utf-8"))
    return str(data["graph_version"])


def _router(node: NodeName) -> Callable[[AgentState], str]:
    def route(state: AgentState) -> str:
        target = next_node(node, state.status)
        return END if target == ROUTE_END else target

    route.__name__ = f"route_after_{node.value.replace('-', '_')}"
    return route


def build_graph() -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    builder = StateGraph(AgentState)
    for name, fn in NODES.items():
        builder.add_node(name.value, cast(Any, fn))
    builder.add_edge(START, NodeName.INTAKE.value)
    for name in NODES:
        if name is NodeName.AUDIT:
            builder.add_edge(name.value, END)
            continue
        targets = sorted(set(ROUTES[name].values()))
        builder.add_conditional_edges(name.value, _router(name), {t: t for t in targets})
    return builder.compile()


@lru_cache
def get_graph() -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    return build_graph()


async def run_agent(request: AgentRequest) -> AgentState:
    """Run one question through the graph and return the final state."""
    initial = AgentState(
        request=request,
        graph_version=graph_version(),
        prompt_versions=dict(get_llm_config().prompts),
    )
    result = await get_graph().ainvoke(initial)
    return AgentState.model_validate(result)
