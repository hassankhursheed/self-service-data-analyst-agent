"""N-01 Request Intake: identity from the request, correlation ID, early rejection.

No LLM call happens here. Disabled users, users without a role and admins are REJECTED
before anything else runs.
"""

import uuid

from pydantic import ValidationError

from app.agent.nodes.base import NodeUpdate, agent_node
from app.agent.state import AgentState
from app.core.context import UserContext
from app.core.enums import BlockReason, NodeName, QuestionStatus, RoleName
from app.safety.sql_policy import BLOCK_MESSAGES


def _reject(reason: BlockReason, correlation_id: uuid.UUID, question: str) -> NodeUpdate:
    return {
        "status": QuestionStatus.REJECTED,
        "correlation_id": correlation_id,
        "question": question,
        "user_message": BLOCK_MESSAGES[reason],
        "block_reason": reason,
    }


@agent_node(NodeName.INTAKE)
async def request_intake(state: AgentState) -> NodeUpdate:
    request = state.request
    correlation_id = request.correlation_id or uuid.uuid4()
    question = request.question
    if not request.is_active:
        return _reject(BlockReason.USER_DISABLED, correlation_id, question)
    if request.role is None:
        return _reject(BlockReason.NO_ROLE, correlation_id, question)
    if request.role is RoleName.ADMIN:
        return _reject(BlockReason.ADMIN_NO_BUSINESS_DATA, correlation_id, question)
    try:
        user = UserContext(
            username=request.username,
            role=request.role,
            region=request.region,
            user_id=request.user_id,
        )
    except ValidationError:
        return _reject(BlockReason.NO_DATA_ACCESS, correlation_id, question)
    return {
        "status": QuestionStatus.RECEIVED,
        "correlation_id": correlation_id,
        "user": user,
        "question": question,
    }
