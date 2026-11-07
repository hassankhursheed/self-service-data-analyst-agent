"""Step 18: API building blocks that need no database."""

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.errors import STATUS_BY_CODE, ApiError, RateLimited, install_error_handlers
from app.api.middleware import HEADER, CorrelationIdMiddleware, parse_correlation_id
from app.api.ratelimit import SlidingWindowLimiter
from app.core.config import ApiConfig


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_rate_limiter_allows_the_limit_then_refuses_until_the_window_passes() -> None:
    clock = Clock()
    limiter = SlidingWindowLimiter(2, window_seconds=60, clock=clock)
    limiter.check("a")
    limiter.check("a")
    with pytest.raises(RateLimited):
        limiter.check("a")
    limiter.check("b")  # keys are independent
    clock.now = 60.0
    limiter.check("a")  # the old hits have left the window


def test_correlation_id_is_kept_when_valid_and_created_otherwise() -> None:
    given = uuid.uuid4()
    assert parse_correlation_id(str(given)) == given
    for bad in (None, "", "not-a-uuid", "1; DROP TABLE x"):
        assert isinstance(parse_correlation_id(bad), uuid.UUID)


def test_every_error_code_used_by_the_services_has_a_status() -> None:
    from app.agent.conversations import ConversationNotFound, NoPendingClarification
    from app.auth.dependencies import AdminOnly
    from app.auth.service import InvalidCredentials
    from app.auth.tokens import InvalidToken, TokenExpired
    from app.services.feedback import QuestionNotFound
    from app.services.review import AlreadyRerun, ErrorNotFound
    from app.services.users import InvalidUserInput, NotAllowed, UsernameTaken, UserNotFound

    expected = {
        InvalidCredentials: 401, InvalidToken: 401, TokenExpired: 401, AdminOnly: 403,
        NotAllowed: 403, ConversationNotFound: 404, UserNotFound: 404, QuestionNotFound: 404,
        ErrorNotFound: 404, UsernameTaken: 409, AlreadyRerun: 409, NoPendingClarification: 409,
        InvalidUserInput: 400, RateLimited: 429,
    }  # fmt: skip
    for error, status in expected.items():
        assert STATUS_BY_CODE[error.code] == status, error


def test_api_config_is_loaded_from_app_yaml() -> None:
    import yaml

    from app.core.config import CONFIG_FILE

    config = ApiConfig.model_validate(yaml.safe_load(CONFIG_FILE.read_text("utf-8"))["api"])
    assert config.cors_origins == ["http://localhost:3000"]
    assert config.rate_limits.questions_per_minute == 20
    assert config.max_page_size >= config.default_page_size


async def test_error_handlers_return_the_standard_shape_without_tracebacks() -> None:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/known")
    async def known() -> None:
        raise ApiError("CONFLICT", "Already done.", detail="internal detail")

    @app.get("/boom")
    async def boom() -> None:
        raise ValueError("internal secret")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        known_response = await client.get("/known")
        assert known_response.status_code == 409
        assert known_response.json()["error"] == {"code": "CONFLICT", "message": "Already done."}
        assert known_response.json()["correlation_id"] == known_response.headers[HEADER]

        boom_response = await client.get("/boom")
        assert boom_response.status_code == 500
        assert boom_response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "secret" not in boom_response.text
        assert boom_response.json()["correlation_id"] == boom_response.headers[HEADER]
