"""N-09 Repair: send the failed SQL and the database error back to the LLM for a fix.

The fix goes through N-07 validation again before it can run. At most
``max_repair_attempts`` repairs; after that the question ends as FAILED.
"""

from app.agent.deps import AgentDeps, usage_of
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.nodes.n06_sql_generation import is_low_confidence
from app.agent.nodes.sql_context import date_range_text, metrics_text, question_text, schema_text
from app.agent.sql_output import GeneratedSQL, check_generated
from app.agent.state import AgentErrorInfo, AgentState, SqlAttempt
from app.core.enums import NodeName, QueryKind, QuestionStatus
from app.core.errors import AppError
from app.core.llm import ainvoke_structured
from app.core.prompts import load_prompt

S = QuestionStatus
REPAIR_LIMIT_MESSAGE = (
    "I couldn't build a working query for this question after several tries. "
    "Please try rephrasing it or asking something simpler."
)


def make_repair_node(deps: AgentDeps) -> NodeFn:
    @agent_node(NodeName.REPAIR)
    async def repair(state: AgentState) -> NodeUpdate:
        config = deps.agent_config.sql
        if state.repair_attempts >= config.max_repair_attempts:
            return {
                "status": S.FAILED,
                "user_message": REPAIR_LIMIT_MESSAGE,
                "error": AgentErrorInfo(
                    node=NodeName.REPAIR,
                    code="REPAIR_LIMIT_REACHED",
                    detail=f"{state.repair_attempts} repairs used; last error: "
                    f"{(state.last_db_error or '')[: config.repair_error_max_chars]}",
                ),
            }
        context = state.context
        if context is None or state.executed_sql is None:
            raise AppError("repair reached without context or failed SQL")
        prompt = load_prompt("sql_repair", deps.llm_config.prompts["sql_repair"])
        messages = [
            *deps.system_messages(),
            *prompt.to_chat_prompt().format_messages(
                schema=schema_text(context),
                metrics=metrics_text(context),
                date_range=date_range_text(state),
                question=question_text(state),
                failed_sql=state.executed_sql,
                error=(state.last_db_error or "unknown error")[: config.repair_error_max_chars],
            ),
        ]
        budget = deps.budget_for(state)
        reply = await ainvoke_structured(
            deps.llm,
            messages,
            GeneratedSQL,
            budget=budget,
            node=NodeName.REPAIR.value,
            max_regenerations=config.max_regenerations,
            check=lambda generated: check_generated(generated, context, state.date_range),
        )
        generated = reply.value
        attempt = SqlAttempt(
            attempt=len(state.sql_attempts) + 1,
            kind=QueryKind.REPAIR,
            sql=generated.sql,
            tables_used=generated.tables_used,
            metrics_used=generated.metrics_used,
            confidence=generated.confidence,
        )
        return {
            "status": S.SQL_GENERATED,
            "via": [S.REPAIRING],
            "generated": generated,
            "sql_attempts": [*state.sql_attempts, attempt],
            "repair_attempts": state.repair_attempts + 1,
            "usage": usage_of(budget),
            "low_confidence": state.low_confidence or is_low_confidence(state, generated),
        }

    return repair
