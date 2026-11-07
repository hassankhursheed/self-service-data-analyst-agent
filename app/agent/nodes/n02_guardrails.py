"""N-02 Input Guardrails: rule-based checks before any LLM call (app/safety/guardrails.py)."""

from app.agent.nodes.base import NodeUpdate, agent_node
from app.agent.state import AgentState, BlockedQueryRecord
from app.core.enums import BlockStage, NodeName, QuestionStatus
from app.core.errors import AppError
from app.safety.guardrails import check_input


@agent_node(NodeName.GUARDRAILS)
async def input_guardrails(state: AgentState) -> NodeUpdate:
    if state.user is None:
        raise AppError("guardrails reached without a user context")
    result = check_input(state.question, state.user.role)
    update: NodeUpdate = {"status": result.status, "guardrail": result, "question": result.question}
    if result.status is QuestionStatus.GUARDRAIL_CHECKED:
        update["notices"] = [*state.notices, *result.notices]
    else:
        update["user_message"] = result.user_message
        update["block_reason"] = result.reason_code
        if result.status is QuestionStatus.BLOCKED and result.reason_code is not None:
            update["blocked"] = BlockedQueryRecord(
                stage=BlockStage.INPUT_GUARDRAIL,
                reason_code=result.reason_code,
                reason_text=result.user_message or "",
                detail=result.matched_rule,
            )
    return update
