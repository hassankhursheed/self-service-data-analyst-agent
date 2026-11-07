"""Step 18: the FastAPI service end to end (real database, scripted LLM, httpx)."""

import dataclasses
import datetime as dt
import json
import re
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.agent.audit import DatabaseAuditSink
from app.agent.checkpoint import checkpoint_serializer
from app.api.deps import Services
from app.api.main import create_app
from app.api.middleware import HEADER
from app.api.ratelimit import SlidingWindowLimiter
from app.auth.tokens import TokenService
from app.core.config import Settings
from app.db.session import create_app_engine, create_session_factory
from scripts.seed import SeedSummary
from tests.fakes import ScriptedModel, fake_deps, intent
from tests.integration.test_sql_path_db import real_executor

pytestmark = pytest.mark.integration
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
COUNT_INTENT = intent(summary="Number of orders", metric="number_of_orders", time_phrase=None)
TOP_CUSTOMERS = intent(
    summary="Top customers",
    metric=None,
    metric_options=["revenue", "number_of_orders"],
    time_phrase=None,
    grouping="customer",
    missing=[{"part": "metric", "reason": "top could mean revenue or number of orders"}],
    clarifying_question="Top customers by revenue or by number of orders?",
    options=["By revenue", "By number of orders"],
)
AFTER_REPLY = intent(summary="Number of orders", metric="number_of_orders", time_phrase=None)
TEST_USERS = ("finance", "operations", "no.role", "admin", "sales.europe")

AppFactory = Callable[..., Any]


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


def services_of(app: FastAPI) -> Services:
    container: Services = app.state.services
    return container


@pytest.fixture
async def make_app(
    settings: Settings,
    analytics_engine: AsyncEngine,
    owner_conn: psycopg.Connection,
) -> AsyncIterator[AppFactory]:
    """Build an app whose agent uses a scripted LLM, the real read-only executor and the
    real audit tables. Cleans up what the tests created."""
    started = dt.datetime.now(dt.UTC)
    audit_engine = create_app_engine(settings)
    sessions = create_session_factory(audit_engine)

    def make(model: ScriptedModel | None = None) -> FastAPI:
        deps = dataclasses.replace(
            fake_deps(model or ScriptedModel(COUNT_INTENT), real_executor(analytics_engine)),
            audit=DatabaseAuditSink(sessions, model_name="scripted", trace_project="tests"),
        )
        return create_app(
            settings, agent_deps=deps, checkpointer=InMemorySaver(serde=checkpoint_serializer())
        )

    yield make
    await audit_engine.dispose()
    owner_conn.execute(
        "DELETE FROM app.conversations WHERE created_at >= %s AND user_id IN "
        "(SELECT id FROM app.users WHERE username = ANY(%s))",
        (started, list(TEST_USERS)),
    )
    owner_conn.execute("DELETE FROM app.agent_errors WHERE created_at >= %s", (started,))
    owner_conn.execute("DELETE FROM app.audit_log WHERE occurred_at >= %s", (started,))


def demo_password(settings: Settings, username: str) -> str:
    secret = settings.demo_password(username)
    assert secret is not None
    return secret.get_secret_value()


async def login(client: AsyncClient, settings: Settings, username: str) -> dict[str, str]:
    response = await client.post(
        "/auth/login", json={"username": username, "password": demo_password(settings, username)}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def assert_correlated(response: Response) -> str:
    """The correlation ID is in the header and the body, and they match."""
    header = response.headers.get(HEADER)
    assert header, response.headers
    assert UUID_RE.match(header)
    assert response.json()["correlation_id"] == header
    return str(header)


def assert_error(response: Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    assert set(body) == {"correlation_id", "error"}
    assert body["error"]["code"] == code
    assert set(body["error"]) == {"code", "message"}
    assert_correlated(response)
    assert "Traceback" not in response.text
    return body


def protected_routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every route in the OpenAPI schema except the two public ones."""
    routes: list[tuple[str, str]] = []
    for path, methods in app.openapi()["paths"].items():
        if path in {"/auth/login", "/health"}:
            continue
        concrete = re.sub(r"\{error_id\}", "1", path)
        concrete = re.sub(r"\{[a-z_]+\}", str(uuid.uuid4()), concrete)
        routes.extend((method.upper(), concrete) for method in methods)
    return routes


# --- authentication and authorisation ---------------------------------------------------


async def test_every_protected_route_refuses_missing_invalid_and_expired_tokens(
    make_app: AppFactory,
    settings: Settings,
) -> None:
    app = make_app()
    tokens = TokenService(settings.jwt_secret_key.get_secret_value(), settings.auth)
    expired = tokens.issue(uuid.uuid4(), 0, now=dt.datetime.now(dt.UTC) - dt.timedelta(days=2))
    cases = [
        ({}, "INVALID_TOKEN"),
        ({"Authorization": "Bearer not-a-jwt"}, "INVALID_TOKEN"),
        ({"Authorization": f"Bearer {expired}"}, "TOKEN_EXPIRED"),
    ]
    async with running(app) as client:
        routes = protected_routes(app)
        assert len(routes) == 22
        for method, path in routes:
            for headers, code in cases:
                response = await client.request(method, path, headers=headers, json={})
                assert_error(response, 401, code)


async def test_non_admins_get_403_on_every_admin_route(
    make_app: AppFactory,
    settings: Settings,
    seeded: SeedSummary,
) -> None:
    app = make_app()
    async with running(app) as client:
        headers = await login(client, settings, "finance")
        admin_routes = [(m, p) for m, p in protected_routes(app) if p.startswith("/admin")]
        assert len(admin_routes) >= 12
        for method, path in admin_routes:
            response = await client.request(method, path, headers=headers, json={})
            assert_error(response, 403, "ADMIN_ONLY")


async def test_login_success_and_failure(
    make_app: AppFactory,
    settings: Settings,
    seeded: SeedSummary,
) -> None:
    async with running(make_app()) as client:
        response = await client.post(
            "/auth/login",
            json={"username": "finance", "password": demo_password(settings, "finance")},
        )
        assert response.status_code == 200
        assert_correlated(response)
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["role"] == "finance_analyst"
        assert "password" not in response.text.lower()

        wrong = await client.post("/auth/login", json={"username": "finance", "password": "nope"})
        assert_error(wrong, 401, "INVALID_CREDENTIALS")
        unknown = await client.post("/auth/login", json={"username": "ghost", "password": "nope"})
        assert unknown.json()["error"] == wrong.json()["error"]  # does not reveal usernames
        assert_error(
            await client.post("/auth/login", json={"username": "x"}), 400, "VALIDATION_ERROR"
        )


# --- questions --------------------------------------------------------------------------


async def test_ask_returns_the_full_answer_model(
    make_app: AppFactory,
    settings: Settings,
    owner_conn: psycopg.Connection,
) -> None:
    async with running(make_app(ScriptedModel(COUNT_INTENT))) as client:
        headers = await login(client, settings, "finance")
        sent_id = str(uuid.uuid4())
        response = await client.post(
            "/ask",
            json={"question": "How many orders are there?"},
            headers={**headers, HEADER: sent_id},
        )
        assert response.status_code == 200, response.text
        assert assert_correlated(response) == sent_id  # a valid client ID is kept
        body = response.json()
        assert body["status"] == "ANSWERED"
        assert body["answer"] == "There were 830 orders."
        assert body["sql"]["text"].lower().startswith("select")
        assert body["table"]["columns"] == ["orders"]
        assert body["table"]["rows"] == [[830]]
        assert body["row_count"] == 1
        for field in (
            "chart",
            "assumptions",
            "notices",
            "date_range",
            "conversation_id",
            "question_id",
            "thread_id",
        ):
            assert field in body
        row = owner_conn.execute(
            "SELECT q.id, q.status, r.final_status FROM app.questions q "
            "JOIN app.agent_runs r ON r.question_id = q.id WHERE q.correlation_id = %s",
            (sent_id,),
        ).fetchone()
        assert row is not None
        assert str(row[0]) == body["question_id"]
        assert row[1:] == ("ANSWERED", "ANSWERED")

        # A follow-up in the same conversation, and an invalid client ID is replaced.
        follow = await client.post(
            "/ask",
            json={"question": "and how many in total?", "conversation_id": body["conversation_id"]},
            headers={**headers, HEADER: "not-a-uuid"},
        )
        assert follow.status_code == 200
        assert assert_correlated(follow) != "not-a-uuid"
        assert follow.json()["conversation_id"] == body["conversation_id"]


async def test_clarify_resumes_the_paused_question(
    make_app: AppFactory,
    settings: Settings,
    seeded: SeedSummary,
) -> None:
    async with running(make_app(ScriptedModel(TOP_CUSTOMERS, AFTER_REPLY))) as client:
        headers = await login(client, settings, "operations")
        paused = await client.post("/ask", json={"question": "Top customers"}, headers=headers)
        assert paused.status_code == 200
        first = paused.json()
        assert first["status"] == "CLARIFICATION_NEEDED"
        assert first["clarification"]["options"] == ["By revenue", "By number of orders"]

        resumed = await client.post(
            "/clarify",
            json={"conversation_id": first["conversation_id"], "answer": "By number of orders"},
            headers=headers,
        )
        assert resumed.status_code == 200, resumed.text
        # Same question, same correlation ID (header and body), now answered.
        assert assert_correlated(resumed) == first["correlation_id"]
        assert resumed.json()["status"] == "ANSWERED"
        assert resumed.json()["question_id"] == first["question_id"]

        again = await client.post(
            "/clarify",
            json={"conversation_id": first["conversation_id"], "answer": "x"},
            headers=headers,
        )
        assert_error(again, 409, "NO_PENDING_CLARIFICATION")
        other = await login(client, settings, "finance")
        stolen = await client.post(
            "/clarify",
            json={"conversation_id": first["conversation_id"], "answer": "x"},
            headers=other,
        )
        assert_error(stolen, 404, "NOT_FOUND")


@pytest.mark.parametrize(("username", "code"), [("no.role", "NO_ROLE"), ("admin", "ADMIN_ONLY")])
async def test_no_role_and_admin_get_403_after_the_rejection_is_audited(
    make_app: AppFactory,
    settings: Settings,
    owner_conn: psycopg.Connection,
    username: str,
    code: str,
) -> None:
    async with running(make_app()) as client:
        headers = await login(client, settings, username)
        response = await client.post("/ask", json={"question": "Revenue in 2024"}, headers=headers)
        correlation_id = assert_error(response, 403, code)["correlation_id"]
    row = owner_conn.execute(
        "SELECT final_status FROM app.agent_runs WHERE correlation_id = %s", (correlation_id,)
    ).fetchone()
    assert row == ("REJECTED",)


async def test_blocked_question_is_listed_for_the_admin(
    make_app: AppFactory,
    settings: Settings,
    seeded: SeedSummary,
) -> None:
    async with running(make_app()) as client:
        finance = await login(client, settings, "finance")
        blocked = await client.post(
            "/ask", json={"question": "Delete all orders from 2023"}, headers=finance
        )
        assert blocked.status_code == 200  # an agent outcome, not an HTTP error
        assert blocked.json()["status"] == "BLOCKED"
        reason = blocked.json()["block"]["reason_code"]

        admin = await login(client, settings, "admin")
        listing = await client.get(
            "/admin/blocked", params={"reason_code": reason, "page_size": 100}, headers=admin
        )
        assert listing.status_code == 200
        assert_correlated(listing)
        items = listing.json()["items"]
        mine = [i for i in items if i["correlation_id"] == blocked.json()["correlation_id"]]
        assert mine
        assert mine[0]["username"] == "finance"
        assert mine[0]["question"] == "Delete all orders from 2023"
        assert listing.json()["total"] >= 1


async def test_conversations_are_listed_and_opened_for_their_owner_only(
    make_app: AppFactory,
    settings: Settings,
    seeded: SeedSummary,
) -> None:
    async with running(make_app()) as client:
        finance = await login(client, settings, "finance")
        asked = (
            await client.post("/ask", json={"question": "How many orders?"}, headers=finance)
        ).json()
        conversation_id = asked["conversation_id"]

        listing = await client.get("/conversations", params={"page_size": 100}, headers=finance)
        assert listing.status_code == 200
        assert any(c["id"] == conversation_id for c in listing.json()["items"])

        detail = await client.get(f"/conversations/{conversation_id}", headers=finance)
        assert detail.status_code == 200
        assert_correlated(detail)
        assert [q["question"] for q in detail.json()["questions"]] == ["How many orders?"]
        assert detail.json()["latest"]["status"] == "ANSWERED"
        table = await client.get(
            f"/conversations/{conversation_id}/table",
            params={"page": 1, "page_size": 10},
            headers=finance,
        )
        assert table.status_code == 200
        assert table.json()["table"]["rows"] == [[830]]
        assert table.json()["table"]["total_pages"] == 1
        me = await client.get("/auth/me", headers=finance)
        assert me.json()["user"]["role"] == "finance_analyst"
        assert_correlated(me)

        operations = await login(client, settings, "operations")
        assert_error(
            await client.get(f"/conversations/{conversation_id}", headers=operations),
            404,
            "NOT_FOUND",
        )
        assert_error(
            await client.get(f"/conversations/{conversation_id}/table", headers=operations),
            404,
            "NOT_FOUND",
        )
        theirs = await client.get("/conversations", params={"page_size": 100}, headers=operations)
        assert all(c["id"] != conversation_id for c in theirs.json()["items"])
        follow = await client.post(
            "/ask",
            json={"question": "and by month?", "conversation_id": conversation_id},
            headers=operations,
        )
        assert_error(follow, 404, "NOT_FOUND")


async def test_feedback_is_stored_for_own_questions_only(
    make_app: AppFactory,
    settings: Settings,
    owner_conn: psycopg.Connection,
) -> None:
    async with running(make_app()) as client:
        finance = await login(client, settings, "finance")
        asked = (
            await client.post("/ask", json={"question": "How many orders?"}, headers=finance)
        ).json()
        body = {
            "question_id": asked["question_id"],
            "rating": "not_helpful",
            "comment": "Missing the discount.",
        }
        first = await client.post("/feedback", json=body, headers=finance)
        assert first.status_code == 200, first.text
        assert_correlated(first)
        again = await client.post("/feedback", json={**body, "rating": "helpful"}, headers=finance)
        assert again.json()["feedback_id"] == first.json()["feedback_id"]  # updated, not added
        row = owner_conn.execute(
            "SELECT rating, comment FROM app.feedback WHERE question_id = %s",
            (asked["question_id"],),
        ).fetchall()
        assert row == [("helpful", "Missing the discount.")]

        operations = await login(client, settings, "operations")
        assert_error(
            await client.post("/feedback", json=body, headers=operations), 404, "NOT_FOUND"
        )
        assert_error(
            await client.post("/feedback", json={**body, "rating": "meh"}, headers=finance),
            400,
            "VALIDATION_ERROR",
        )


# --- admin ------------------------------------------------------------------------------


async def test_rerun_runs_the_logged_question_as_the_original_user(
    make_app: AppFactory,
    settings: Settings,
    owner_conn: psycopg.Connection,
) -> None:
    finance_id = owner_conn.execute(
        "SELECT id FROM app.users WHERE username = 'finance'"
    ).fetchone()
    assert finance_id is not None
    original = uuid.uuid4()
    snapshot: dict[str, Any] = {
        "request": {
            "username": "finance",
            "role": "finance_analyst",
            "region": None,
            "is_active": True,
            "question": "How many orders?",
            "user_id": str(finance_id[0]),
            "conversation_id": None,
            "correlation_id": str(original),
        },
        "clarifications": [],
        "thread_id": None,
    }
    error_id = owner_conn.execute(
        "INSERT INTO app.agent_errors (correlation_id, node_name, error_type, retryable, "
        "error_message, input_snapshot) VALUES (%s, 'N-06', 'RETRYABLE', true, 'LLM timeout', %s) "
        "RETURNING id",
        (original, json.dumps(snapshot)),
    ).fetchone()
    assert error_id is not None

    async with running(make_app()) as client:
        admin = await login(client, settings, "admin")
        listing = await client.get(
            "/admin/errors", params={"status": "open", "page_size": 100}, headers=admin
        )
        assert any(i["id"] == error_id[0] for i in listing.json()["items"])

        response = await client.post(f"/admin/errors/{error_id[0]}/rerun", headers=admin)
        assert response.status_code == 202, response.text
        correlation_id = assert_correlated(response)
        assert response.json()["status"] == "ANSWERED"
        again = await client.post(f"/admin/errors/{error_id[0]}/rerun", headers=admin)
        assert_error(again, 409, "CONFLICT")
        assert_error(
            await client.post("/admin/errors/999999999/rerun", headers=admin), 404, "NOT_FOUND"
        )

    question = owner_conn.execute(
        "SELECT u.username, q.role_name, q.status FROM app.questions q "
        "JOIN app.users u ON u.id = q.user_id WHERE q.correlation_id = %s",
        (correlation_id,),
    ).fetchone()
    assert question == ("finance", "finance_analyst", "ANSWERED")  # ran as finance, not admin
    status = owner_conn.execute(
        "SELECT status FROM app.agent_errors WHERE id = %s", (error_id[0],)
    ).fetchone()
    assert status == ("rerun",)
    event = owner_conn.execute(
        "SELECT count(*) FROM app.audit_log WHERE event_type = 'error_rerun' AND target_id = %s",
        (str(error_id[0]),),
    ).fetchone()
    assert event == (1,)


async def test_admin_user_management_round_trip(
    make_app: AppFactory,
    settings: Settings,
    seeded: SeedSummary,
    owner_conn: psycopg.Connection,
) -> None:
    owner_conn.execute("DELETE FROM app.users WHERE username = 'test.api.user'")
    try:
        async with running(make_app()) as client:
            admin = await login(client, settings, "admin")
            created = await client.post(
                "/admin/users",
                headers=admin,
                json={
                    "username": "test.api.user",
                    "display_name": "API Test",
                    "password": "a-long-password-1",
                    "role": "sales_manager",
                    "region": "EUROPE",
                },
            )
            assert created.status_code == 201, created.text
            assert_correlated(created)
            user_id = created.json()["id"]
            duplicate = await client.post(
                "/admin/users",
                headers=admin,
                json={
                    "username": "test.api.user",
                    "password": "a-long-password-1",
                    "role": "finance_analyst",
                },
            )
            assert_error(duplicate, 409, "USERNAME_TAKEN")
            weak = await client.post(
                "/admin/users",
                headers=admin,
                json={"username": "test.api.weak", "password": "short", "role": "finance_analyst"},
            )
            assert_error(weak, 400, "VALIDATION_ERROR")

            changed = await client.patch(
                f"/admin/users/{user_id}",
                headers=admin,
                json={"role": "finance_analyst", "region": None},
            )
            assert changed.json()["role"] == "finance_analyst"
            disabled = await client.patch(
                f"/admin/users/{user_id}", headers=admin, json={"is_active": False}
            )
            assert disabled.json()["is_active"] is False
            reset = await client.post(
                f"/admin/users/{user_id}/reset-password",
                headers=admin,
                json={"new_password": "another-long-password"},
            )
            assert reset.status_code == 200
            listing = await client.get("/admin/users", params={"is_active": False}, headers=admin)
            assert any(u["id"] == user_id for u in listing.json()["items"])
            assert_error(
                await client.patch(
                    f"/admin/users/{uuid.uuid4()}", headers=admin, json={"is_active": True}
                ),
                404,
                "NOT_FOUND",
            )
    finally:
        owner_conn.execute("DELETE FROM app.users WHERE username = 'test.api.user'")


async def test_later_step_routes_return_501_with_a_correlation_id(
    make_app: AppFactory,
    settings: Settings,
    seeded: SeedSummary,
) -> None:
    async with running(make_app()) as client:
        admin = await login(client, settings, "admin")
        for method, path, body in [
            ("POST", "/admin/eval/run", {"dataset": "northwind-eval", "experiment_name": "x"}),
            ("GET", "/admin/eval/runs", None),
        ]:
            response = await client.request(method, path, headers=admin, json=body)
            assert_error(response, 501, "NOT_IMPLEMENTED")


# --- platform behaviour -----------------------------------------------------------------


async def test_unexpected_errors_return_a_generic_500_without_details(
    make_app: AppFactory,
    settings: Settings,
    seeded: SeedSummary,
) -> None:
    app = make_app()
    async with running(app) as client:
        headers = await login(client, settings, "finance")

        async def explode(*_: object, **__: object) -> None:
            raise RuntimeError("secret internal detail at /srv/app.py line 42")

        conversations = services_of(app).conversations
        conversations.ask = explode  # type: ignore[method-assign,assignment]
        response = await client.post("/ask", json={"question": "How many orders?"}, headers=headers)
        body = assert_error(response, 500, "INTERNAL_ERROR")
        assert "secret" not in response.text
        assert "line 42" not in response.text
        assert body["error"]["message"].startswith("Something went wrong")


async def test_health_reports_the_database(make_app: AppFactory, settings: Settings) -> None:
    app = make_app()
    async with running(app) as client:
        ok = await client.get("/health")
        assert ok.status_code == 200
        assert_correlated(ok)
        assert ok.json()["database"] == "ok"

        services = services_of(app)
        down = create_async_engine(
            "postgresql+asyncpg://nobody:x@127.0.0.1:1/none", connect_args={"timeout": 2}
        )
        app.state.services = dataclasses.replace(services, engine=down)
        degraded = await client.get("/health")
        assert degraded.status_code == 503
        assert_correlated(degraded)
        assert degraded.json()["status"] == "degraded"
        assert degraded.json()["database"] == "down"
        await down.dispose()


async def test_cors_allows_only_the_ui_origin(make_app: AppFactory) -> None:
    preflight = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }
    async with running(make_app()) as client:
        allowed = await client.options(
            "/ask", headers={"Origin": "http://localhost:3000", **preflight}
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
        refused = await client.options(
            "/ask", headers={"Origin": "https://evil.example", **preflight}
        )
        assert "access-control-allow-origin" not in refused.headers
        simple = await client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert HEADER.lower() in simple.headers["access-control-expose-headers"].lower()


async def test_logins_and_questions_are_rate_limited(
    make_app: AppFactory,
    settings: Settings,
    seeded: SeedSummary,
) -> None:
    app = make_app()
    async with running(app) as client:
        headers = await login(client, settings, "finance")
        app.state.services = dataclasses.replace(
            services_of(app),
            login_limiter=SlidingWindowLimiter(1),
            question_limiter=SlidingWindowLimiter(1),
        )
        body = {"username": "finance", "password": "wrong"}
        assert (await client.post("/auth/login", json=body)).status_code == 401
        assert_error(await client.post("/auth/login", json=body), 429, "RATE_LIMITED")
        assert (
            await client.post("/ask", json={"question": "How many orders?"}, headers=headers)
        ).status_code == 200
        assert_error(
            await client.post("/ask", json={"question": "How many orders?"}, headers=headers),
            429,
            "RATE_LIMITED",
        )


async def test_unknown_routes_use_the_error_shape(make_app: AppFactory) -> None:
    async with running(make_app()) as client:
        assert_error(await client.get("/nope"), 404, "NOT_FOUND")
        assert_error(await client.delete("/health"), 405, "METHOD_NOT_ALLOWED")
        docs = await client.get("/openapi.json")
        assert docs.status_code == 200
        assert "/ask" in docs.json()["paths"]
