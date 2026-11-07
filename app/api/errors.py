"""One error shape for every response: ``{correlation_id, error: {code, message}}``.

Status codes come from the error's stable ``code``. Bodies never contain stack traces;
unexpected errors get a generic message and are logged with the correlation ID.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError

logger = logging.getLogger(__name__)

STATUS_BY_CODE: dict[str, int] = {
    "VALIDATION_ERROR": 400,
    "SQL_INVALID": 400,
    "QUESTION_EMPTY": 400,
    "QUESTION_TOO_LONG": 400,
    "INVALID_CREDENTIALS": 401,
    "INVALID_TOKEN": 401,
    "TOKEN_EXPIRED": 401,
    "ADMIN_ONLY": 403,
    "NO_ROLE": 403,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "METHOD_NOT_ALLOWED": 405,
    "USERNAME_TAKEN": 409,
    "CONFLICT": 409,
    "NO_PENDING_CLARIFICATION": 409,
    "RATE_LIMITED": 429,
    "NOT_IMPLEMENTED": 501,
    "SERVICE_UNAVAILABLE": 503,
}
GENERIC_MESSAGE = "Something went wrong. Please try again; the team has been notified."


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    correlation_id: str
    error: ErrorDetail


class ApiError(AppError):
    """An error raised by a route with an explicit code and message."""

    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(detail or code, user_message=message)
        self.code = code


class RateLimited(AppError):
    code = "RATE_LIMITED"
    user_message = "Too many requests. Please wait a moment and try again."


class NotImplementedYet(AppError):
    code = "NOT_IMPLEMENTED"
    user_message = "This feature is not available yet."


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` entries: these statuses return ErrorResponse."""
    return {status: {"model": ErrorResponse} for status in statuses}


def correlation_id_of(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", ""))


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(
        correlation_id=correlation_id_of(request), error=ErrorDetail(code=code, message=message)
    )
    return JSONResponse(status_code=status, content=body.model_dump())


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        status = STATUS_BY_CODE.get(exc.code, 500)
        if status >= 500 and exc.code not in {"NOT_IMPLEMENTED", "SERVICE_UNAVAILABLE"}:
            logger.error("error %s for correlation_id=%s: %s", exc.code, correlation_id_of(request),
                         exc.detail)  # fmt: skip
        return error_response(request, status, exc.code, exc.user_message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted({".".join(str(p) for p in e["loc"] if p != "body") for e in exc.errors()})
        message = "Some fields are missing or not valid: " + ", ".join(f for f in fields if f)
        return error_response(request, 400, "VALIDATION_ERROR", message.rstrip(": "))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        message = {404: "Not found.", 405: "Method not allowed."}.get(
            exc.status_code, "Request failed."
        )
        return error_response(request, exc.status_code, code, message)
