"""Question length check, run before anything else touches the question."""

from pydantic import BaseModel, ConfigDict

from app.core.enums import BlockReason
from app.safety.sql_policy import BLOCK_MESSAGES, SqlPolicy, get_sql_policy


class QuestionCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    question: str
    reason_code: BlockReason | None = None
    user_message: str | None = None


def validate_question(text: str, policy: SqlPolicy | None = None) -> QuestionCheck:
    """Reject empty or too-long questions. Returns the trimmed question when allowed."""
    policy = policy or get_sql_policy()
    question = (text or "").strip()
    reason: BlockReason | None = None
    if not question:
        reason = BlockReason.QUESTION_EMPTY
    elif len(question) > policy.max_question_length:
        reason = BlockReason.QUESTION_TOO_LONG
    if reason is None:
        return QuestionCheck(allowed=True, question=question)
    return QuestionCheck(
        allowed=False, question=question, reason_code=reason, user_message=BLOCK_MESSAGES[reason]
    )
