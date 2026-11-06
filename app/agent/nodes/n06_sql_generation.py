"""N-06 SQL Generation: structured SQL from the LLM (brief section 15).

Only the schema of the retrieved tables, metric definitions and the resolved period are
sent. The reply must match ``GeneratedSQL`` and stay inside the retrieved context; one
regeneration is allowed, then the question fails with a clear reason. Nothing runs here.
"""

from app.agent.deps import AgentDeps, usage_of
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.nodes.sql_context import date_range_text, metrics_text, question_text, schema_text
from app.agent.sql_output import GeneratedSQL, check_against_context
from app.agent.state import AgentState
from app.core.enums import Confidence, NodeName, QuestionStatus
from app.core.errors import AppError
from app.core.llm import ainvoke_structured
from app.core.prompts import load_prompt


def is_low_confidence(state: AgentState, generated: GeneratedSQL) -> bool:
    """Low when the model says so, or when its period differs from the resolved one."""
    if generated.confidence is Confidence.LOW:
        return True
    if state.date_range is not None and generated.date_range is not None:
        return (generated.date_range.from_date, generated.date_range.to_date) != (
            state.date_range.from_date,
            state.date_range.to_date,
        )
    return False


def make_sql_generation_node(deps: AgentDeps) -> NodeFn:
    @agent_node(NodeName.SQL_GENERATION)
    async def sql_generation(state: AgentState) -> NodeUpdate:
        context = state.context
        if context is None:
            raise AppError("SQL generation reached without a context")
        prompt = load_prompt("sql_generation", deps.llm_config.prompts["sql_generation"])
        messages = [
            *deps.system_messages(),
            *prompt.to_chat_prompt().format_messages(
                schema=schema_text(context),
                metrics=metrics_text(context),
                date_range=date_range_text(state),
                assumptions="; ".join(state.assumptions) or "none",
                top_n=str(state.top_n) if state.top_n else "not given",
                question=question_text(state),
            ),
        ]
        budget = deps.budget_for(state)
        reply = await ainvoke_structured(
            deps.llm,
            messages,
            GeneratedSQL,
            budget=budget,
            node=NodeName.SQL_GENERATION.value,
            max_regenerations=deps.agent_config.sql.max_regenerations,
            check=lambda generated: check_against_context(generated, context),
        )
        generated = reply.value
        return {
            "status": QuestionStatus.SQL_GENERATED,
            "generated": generated,
            "usage": usage_of(budget),
            "regeneration_attempts": state.regeneration_attempts + reply.regenerations,
            "low_confidence": state.low_confidence or is_low_confidence(state, generated),
            "assumptions": [*state.assumptions, *generated.assumptions],
        }

    return sql_generation
