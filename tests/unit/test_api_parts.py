"""Step 18: API building blocks that need no database."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.api.deps import client_ip, forwarded_client_ip
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


def test_p95_uses_linear_interpolation_like_percentile_cont() -> None:
    from app.services.metrics import p95

    assert p95([]) is None
    assert p95([42.0]) == 42.0
    assert p95([10.0 * i for i in range(1, 21)]) == 190.5
    assert p95([100.0, 300.0, 400.0, 500.0, 600.0]) == 580.0
    assert p95([5.0, 1.0, 3.0]) == 4.8  # order does not matter: 3 + 0.9 * (5 - 3)


def test_every_endpoint_is_async() -> None:
    """Step 24: no route blocks the event loop with a sync handler."""
    import inspect

    from fastapi.routing import APIRoute

    from app.api.routes import admin, public, questions

    routes = [
        r for m in (public, questions, admin) for r in m.router.routes if isinstance(r, APIRoute)
    ]
    assert len(routes) >= 24
    sync = [r.path for r in routes if not inspect.iscoroutinefunction(r.endpoint)]
    assert sync == []


def _request(trust: bool | None, headers: dict[str, str]) -> Request:
    app = FastAPI()
    if trust is not None:
        app.state.services = SimpleNamespace(api=SimpleNamespace(trust_forwarded_for=trust))
    scope = {
        "type": "http",
        "app": app,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("10.0.0.5", 1234),
    }
    return Request(scope)


def test_client_ip_ignores_forwarded_addresses_unless_trusted() -> None:
    forwarded = {"X-Forwarded-For": "203.0.113.7"}
    assert client_ip(_request(False, forwarded)) == "10.0.0.5"
    assert client_ip(_request(None, forwarded)) == "10.0.0.5"
    assert client_ip(_request(True, forwarded)) == "203.0.113.7"


def test_client_ip_uses_the_last_forwarded_entry_and_rejects_garbage() -> None:
    assert client_ip(_request(True, {"X-Forwarded-For": "6.6.6.6, 2001:db8::1"})) == "2001:db8::1"
    assert client_ip(_request(True, {"X-Forwarded-For": "not-an-ip"})) == "10.0.0.5"
    assert client_ip(_request(True, {})) == "10.0.0.5"
    assert forwarded_client_ip(None) is None
