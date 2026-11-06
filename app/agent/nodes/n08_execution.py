"""N-08 Execution: run the validated SQL as the read-only role for this user only.

- success: EXECUTED
- database error: EXECUTION_FAILED (N-09 may repair it)
- statement timeout: FAILED with a clear message (not repaired)
- refused by the database (permissions, read-only): BLOCKED, recorded
- database unreachable: retried with backoff, then FAILED
"""

from sqlalchemy.exc import DBAPIError, OperationalError

from app.agent.deps import AgentDeps
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.state import AgentErrorInfo, AgentState, BlockedQueryRecord
from app.core.context import UserContext
from app.core.enums import BlockReason, BlockStage, NodeName, QuestionStatus
from app.core.errors import AppError, DbTimeout, RetryableError
from app.db.analytics import QueryResult, ReadonlyQueryError
from app.safety.sql_policy import BLOCK_MESSAGES

S = QuestionStatus
_REFUSED = {"permission_denied", "read_only", "no_data_access"}


def make_execution_node(deps: AgentDeps) -> NodeFn:
    async def run_with_retry(sql: str, user: UserContext) -> QueryResult:
        config = deps.agent_config.sql
        for attempt in range(1, config.db_connect_attempts + 1):
            try:
                return await deps.executor(sql, user, deps.statement_timeout_ms, deps.row_limit)
            except (OSError, OperationalError, ConnectionError) as exc:
                if attempt == config.db_connect_attempts:
                    raise RetryableError(f"database not reachable: {type(exc).__name__}") from exc
                await deps.sleep(config.db_connect_backoff_seconds * attempt)
            except DBAPIError as exc:
                if not exc.connection_invalidated or attempt == config.db_connect_attempts:
                    raise
                await deps.sleep(config.db_connect_backoff_seconds * attempt)
        raise RetryableError("database not reachable")

    @agent_node(NodeName.EXECUTION)
    async def execution(state: AgentState) -> NodeUpdate:
        if state.user is None or state.validation is None or not state.validation.final_sql:
            raise AppError("execution reached without validated SQL")
        sql = state.validation.final_sql
        try:
            result = await run_with_retry(sql, state.user)
        except ReadonlyQueryError as err:
            if err.kind == "timeout":
                return {
                    "status": S.FAILED,
                    "executed_sql": sql,
                    "user_message": DbTimeout.user_message,
                    "error": AgentErrorInfo(
                        node=NodeName.EXECUTION, code=DbTimeout.code, detail=err.message
                    ),
                }
            if err.kind in _REFUSED:
                reason = BlockReason.DATABASE_REFUSED
                return {
                    "status": S.BLOCKED,
                    "executed_sql": sql,
                    "block_reason": reason,
                    "user_message": BLOCK_MESSAGES[reason],
                    "blocked": BlockedQueryRecord(
                        stage=BlockStage.SQL_VALIDATION,
                        reason_code=reason,
                        reason_text=BLOCK_MESSAGES[reason],
                        sql=sql,
                        detail=f"{err.kind}: {err.message}",
                    ),
                }
            return {"status": S.EXECUTION_FAILED, "executed_sql": sql, "last_db_error": err.message}
        return {
            "status": S.EXECUTED,
            "execution": result,
            "executed_sql": sql,
            "last_db_error": None,
        }

    return execution
