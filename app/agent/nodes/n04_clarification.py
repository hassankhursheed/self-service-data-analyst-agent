"""N-04 Clarification: ask one question with 2-4 options and pause until the user replies.

The pause is a LangGraph ``interrupt``. On resume this node runs again, receives the reply
(an option or free text), stores the question and answer, and hands back to N-03, which
analyses the question again with the answer included.
"""

import datetime as dt

from langgraph.types import interrupt

from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.state import AgentState, ClarificationRecord
from app.core.enums import NodeName, QuestionStatus
from app.core.errors import AppError


def make_clarification_node() -> NodeFn:
    @agent_node(NodeName.CLARIFICATION)
    async def clarification(state: AgentState) -> NodeUpdate:
        draft = state.pending_clarification
        if draft is None:
            raise AppError("clarification reached without a question to ask")
        round_number = len(state.clarifications) + 1
        asked_at = dt.datetime.now(dt.UTC)
        reply = interrupt(
            {
                "question": draft.question,
                "options": list(draft.options),
                "round": round_number,
                "missing_parts": list(draft.missing_parts),
            }
        )
        record = ClarificationRecord(
            round=round_number,
            question=draft.question,
            options=list(draft.options),
            missing_parts=list(draft.missing_parts),
            asked_at=asked_at,
            answer=str(reply).strip(),
            answered_at=dt.datetime.now(dt.UTC),
        )
        return {
            "status": QuestionStatus.CLARIFICATION_NEEDED,
            "clarifications": [*state.clarifications, record],
            "pending_clarification": None,
            "user_message": None,
        }

    return clarification
