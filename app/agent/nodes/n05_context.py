"""N-05 Context Retrieval: semantic-layer lookup for the user's role (Step 7 retriever).

The semantic layer is loaded fresh for each question (from the database in production),
so a changed metric definition takes effect without a code change or restart.
"""

from app.agent.deps import AgentDeps
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.state import AgentState, BlockedQueryRecord
from app.core.enums import BlockReason, BlockStage, NodeName, QuestionStatus, RoleName
from app.core.errors import AppError
from app.safety.sql_policy import BLOCK_MESSAGES
from app.semantic.retriever import retrieve


def find_verified_examples(question: str, role: RoleName) -> list[str]:
    """Hook for the verified query library (Step 20). Returns no examples until then."""
    return []


def _retrieval_text(state: AgentState) -> str:
    parts = [state.question, state.interpreted_question or ""]
    if state.intent is not None:
        parts.append(state.intent.summary)
        if state.intent.metric:
            parts.append(state.intent.metric.replace("_", " "))
        if state.intent.grouping:
            parts.append(state.intent.grouping)
        parts.extend(state.intent.entities)
    parts.extend(c.answer for c in state.clarifications if c.answer)
    return " ".join(parts)


def make_context_node(deps: AgentDeps) -> NodeFn:
    @agent_node(NodeName.CONTEXT)
    async def context_retrieval(state: AgentState) -> NodeUpdate:
        if state.user is None:
            raise AppError("context retrieval reached without a user context")
        layer = await deps.load_semantic()
        context = retrieve(_retrieval_text(state), state.user.role, layer)
        if not context.tables:
            reason = BlockReason.NO_ALLOWED_DATA
            return {
                "status": QuestionStatus.BLOCKED,
                "semantic": layer,
                "context": context,
                "block_reason": reason,
                "user_message": BLOCK_MESSAGES[reason],
                "blocked": BlockedQueryRecord(
                    stage=BlockStage.CONTEXT,
                    reason_code=reason,
                    reason_text=BLOCK_MESSAGES[reason],
                    detail="no table matched the question for this role",
                ),
            }
        return {
            "status": QuestionStatus.UNDERSTOOD,
            "semantic": layer,
            "context": context,
            "verified_examples": find_verified_examples(state.question, state.user.role),
        }

    return context_retrieval
