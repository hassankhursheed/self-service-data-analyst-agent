"""N-05 Context Retrieval: semantic-layer lookup for the user's role (Step 7 retriever).

The semantic layer is loaded fresh for each question (from the database in production),
so a changed metric definition takes effect without a code change or restart.
"""

import logging

from app.agent.deps import AgentDeps
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.state import AgentState, BlockedQueryRecord
from app.core.enums import BlockReason, BlockStage, NodeName, QuestionStatus, RoleName
from app.core.errors import AppError
from app.safety.sql_policy import BLOCK_MESSAGES
from app.semantic.models import SemanticLayer
from app.semantic.retriever import retrieve
from app.semantic.verified import VerifiedExample, find_verified_examples

logger = logging.getLogger(__name__)


async def _verified_examples(
    deps: AgentDeps, state: AgentState, role: RoleName, layer: SemanticLayer
) -> list[VerifiedExample]:
    """Similar verified examples for this role; the library is optional guidance, so a
    loading problem is logged and the question continues without examples."""
    config = deps.agent_config.verified_examples
    if not config.enabled:
        return []
    try:
        library = await deps.load_verified()
    except Exception:  # any storage problem must not fail the question
        logger.exception("could not load verified examples (correlation_id=%s)",
                         state.correlation_id)  # fmt: skip
        return []
    question = state.interpreted_question or state.question
    return find_verified_examples(question, role, library, layer, config, deps.sql_policy)


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
            "verified_examples": await _verified_examples(deps, state, state.user.role, layer),
        }

    return context_retrieval
