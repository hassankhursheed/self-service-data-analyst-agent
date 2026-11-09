"""N-06 SQL Generation: structured SQL from the LLM (brief section 15).

Only the schema of the retrieved tables, metric definitions, the resolved period and the
verified examples chosen by N-05 (few-shot guidance) are sent. The reply must match
``GeneratedSQL`` and stay inside the retrieved context; one
regeneration is allowed, then the question fails with a clear reason. Nothing runs here.
"""

from app.agent.deps import AgentDeps, usage_of
from app.agent.intent import merge_assumptions
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.nodes.sql_context import (
    assumptions_for_sql,
    date_range_text,
    metrics_text,
    question_text,
    schema_text,
)
from app.agent.sql_output import GeneratedSQL, check_generated
from app.agent.state import AgentState, SqlAttempt
from app.core.enums import Confidence, NodeName, QueryKind, QuestionStatus
from app.core.errors import AppError
from app.core.llm import ainvoke_structured
from app.core.prompts import load_prompt
from app.semantic.verified import examples_text


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
                assumptions="; ".join(assumptions_for_sql(state)) or "none",
                top_n=str(state.top_n) if state.top_n else "not given",
                examples=examples_text(state.verified_examples),
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
            check=lambda generated: check_generated(generated, context, state.date_range),
        )
        generated = reply.value
        attempt = SqlAttempt(
            attempt=len(state.sql_attempts) + 1,
            kind=QueryKind.INITIAL,
            sql=generated.sql,
            tables_used=generated.tables_used,
            metrics_used=generated.metrics_used,
            confidence=generated.confidence,
            verified_examples=[str(example.id) for example in state.verified_examples],
        )
        return {
            "status": QuestionStatus.SQL_GENERATED,
            "generated": generated,
            "sql_attempts": [*state.sql_attempts, attempt],
            "usage": usage_of(budget),
            "regeneration_attempts": state.regeneration_attempts + reply.regenerations,
            "low_confidence": state.low_confidence or is_low_confidence(state, generated),
            "assumptions": merge_assumptions(state.assumptions, generated.assumptions),
        }

    return sql_generation
