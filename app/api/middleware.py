"""Correlation ID for every request: accepted from ``X-Correlation-ID`` or created here.

It is stored on ``request.state``, returned in the response header and in every body, and
handed to the agent (so it also links the audit rows and the LangSmith trace). Unexpected
errors are turned into the standard error body here, so even a 500 carries the ID.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.errors import GENERIC_MESSAGE, error_response

HEADER = "X-Correlation-ID"
logger = logging.getLogger(__name__)


def parse_correlation_id(value: str | None) -> uuid.UUID:
    if value:
        try:
            return uuid.UUID(value)
        except ValueError:
            pass
    return uuid.uuid4()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = parse_correlation_id(request.headers.get(HEADER))
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error for correlation_id=%s", correlation_id)
            response = error_response(request, 500, "INTERNAL_ERROR", GENERIC_MESSAGE)
        # A route may switch to the ID of the run it continues (POST /clarify).
        response.headers[HEADER] = str(getattr(request.state, "correlation_id", correlation_id))
        return response
