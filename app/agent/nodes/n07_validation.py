"""N-07 SQL Validation and Policy: the Step 9 validator decides; nothing else runs SQL."""

from app.agent.deps import AgentDeps
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.state import AgentState, BlockedQueryRecord
from app.core.enums import BlockReason, BlockStage, NodeName, QuestionStatus
from app.core.errors import AppError
from app.safety.sql_validator import validate


def make_validation_node(deps: AgentDeps) -> NodeFn:
    @agent_node(NodeName.VALIDATION)
    async def sql_validation(state: AgentState) -> NodeUpdate:
        if state.user is None or state.generated is None or state.semantic is None:
            raise AppError("validation reached without user, SQL or semantic layer")
        result = validate(state.generated.sql, state.user.role, state.semantic, deps.sql_policy)
        if not result.allowed:
            reason = result.reason_code or BlockReason.PARSE_ERROR
            message = result.user_message or "This query is not allowed."
            return {
                "status": QuestionStatus.BLOCKED,
                "validation": result,
                "block_reason": reason,
                "user_message": message,
                "blocked": BlockedQueryRecord(
                    stage=BlockStage.SQL_VALIDATION,
                    reason_code=reason,
                    reason_text=message,
                    sql=state.generated.sql,
                    detail=result.detail,
                ),
            }
        return {"status": QuestionStatus.VALIDATED, "validation": result}

    return sql_validation
