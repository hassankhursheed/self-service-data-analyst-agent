"""Error taxonomy shared by the agent (brief section 22).

- ``RetryableError``: temporary failure (timeout, rate limit, 5xx, connection); retried
  with backoff, then recorded in AgentErrors.
- ``NonRetryableError``: invalid request or authentication; fails at once.
- ``BudgetExceeded``: the question's token or cost budget is used up.
- ``DbTimeout``: a database statement ran past its timeout.
- ``ValidationBlocked``: a question or query was refused by a safety check.

Every error carries a stable ``code`` for logs and a ``user_message`` that is safe to show.
"""

from app.core.enums import BlockReason


class AppError(Exception):
    code = "APP_ERROR"
    user_message = "Something went wrong. Please try again."

    def __init__(self, detail: str = "", *, user_message: str | None = None) -> None:
        super().__init__(detail or self.code)
        self.detail = detail
        if user_message is not None:
            self.user_message = user_message


class RetryableError(AppError):
    code = "RETRYABLE"
    user_message = "The AI service is busy or slow right now. Please try again in a moment."


class NonRetryableError(AppError):
    code = "NON_RETRYABLE"
    user_message = "The AI service could not process this request."


class BudgetExceeded(AppError):
    code = "BUDGET_EXCEEDED"
    user_message = "This question needed more AI processing than allowed. Please simplify it."


class DbTimeout(AppError):
    code = "DB_TIMEOUT"
    user_message = "The query took too long and was stopped. Try a narrower question."


class ValidationBlocked(AppError):
    code = "VALIDATION_BLOCKED"

    def __init__(self, reason: BlockReason, detail: str = "", *, user_message: str) -> None:
        super().__init__(detail or reason.value, user_message=user_message)
        self.reason = reason
