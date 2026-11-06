"""Wrapper shared by every node: transition guard, step record and failure handling."""

import datetime as dt
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from pydantic import BaseModel

from app.agent.state import AgentErrorInfo, AgentState, StepRecord
from app.agent.transitions import IllegalTransition, check_transition
from app.core.enums import NodeName, QuestionStatus
from app.core.errors import AppError

NodeUpdate = dict[str, Any]
NodeFn = Callable[[AgentState], Awaitable[NodeUpdate]]

_MAX_TEXT = 200


def summarize(value: Any) -> Any:  # noqa: ANN401 (summaries are any JSON-like value)
    """Small, log-safe summary of a value for the step record (long text is cut)."""
    if isinstance(value, BaseModel):
        return summarize(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(k): summarize(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [summarize(v) for v in value[:10]] + (["..."] if len(value) > 10 else [])
    if isinstance(value, str) and len(value) > _MAX_TEXT:
        return value[:_MAX_TEXT] + "..."
    if isinstance(value, int | float | bool) or value is None:
        return value
    return str(value)


def agent_node(name: NodeName) -> Callable[[NodeFn], NodeFn]:
    """Turn ``fn(state) -> update`` into a graph node with guard and step record.

    The update may set ``status`` (checked against the transition table) and an optional
    ``via`` list of intermediate statuses (e.g. REPAIRING). Unexpected errors end the
    question as FAILED with a safe message; illegal transitions are bugs and are raised.
    """

    def decorate(fn: NodeFn) -> NodeFn:
        @wraps(fn)
        async def run(state: AgentState) -> NodeUpdate:
            started_at = dt.datetime.now(dt.UTC)
            start = time.perf_counter()
            before = state.status
            error_code: str | None = None
            try:
                update = dict(await fn(state))
            except IllegalTransition:
                raise
            except AppError as exc:
                error_code = exc.code
                update = _failed(name, exc.code, exc.detail, exc.user_message, exc)
            except Exception as exc:  # unexpected: never leak details to the user
                error_code = "INTERNAL_ERROR"
                update = _failed(
                    name, error_code, f"{type(exc).__name__}: {exc}",
                    "Something went wrong while answering. The team has been notified.", exc,
                )  # fmt: skip
            via: list[QuestionStatus] = update.pop("via", [])
            after: QuestionStatus | None = update.get("status", before)
            if after is not None and (after != before or via):
                check_transition(before, after, name, via)
            record = StepRecord(
                node=name,
                from_status=before,
                to_status=after,
                started_at=started_at,
                ended_at=dt.datetime.now(dt.UTC),
                duration_ms=round((time.perf_counter() - start) * 1000, 3),
                input_summary={"status": before.value if before else None},
                output_summary=summarize({k: v for k, v in update.items() if k != "steps"}),
                error_code=error_code,
            )
            update["steps"] = [record]
            return update

        return run

    return decorate


def _failed(
    node: NodeName, code: str, detail: str, user_message: str, exc: Exception
) -> NodeUpdate:
    from app.core.errors import RetryableError

    return {
        "status": QuestionStatus.FAILED,
        "error": AgentErrorInfo(
            node=node, code=code, detail=detail, retryable=isinstance(exc, RetryableError)
        ),
        "user_message": user_message,
    }
