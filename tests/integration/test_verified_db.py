"""Step 20: verified examples end to end (real database, scripted LLM, API).

Scenario 10: a question similar to a verified example uses it and returns the correct result.
Scenario 11: a not-helpful answer appears in the review list and becomes an eval case.
"""

import dataclasses
import datetime as dt
import uuid
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.audit import DatabaseAuditSink
from app.agent.checkpoint import checkpoint_serializer
from app.agent.memory import app_role_conninfo
from app.api.main import create_app
from app.core.config import Settings
from app.db.session import create_app_engine, create_session_factory
from app.semantic.verified import database_verified_loader, lineage_for
from scripts.seed import SeedSummary
from tests.fakes import ScriptedModel, fake_deps, intent, sql_reply
from tests.integration.test_api import assert_correlated, assert_error, login, running
from tests.integration.test_sql_path_db import real_executor

pytestmark = pytest.mark.integration
REVENUE_Q1 = intent(
    summary="Total revenue last quarter", metric="revenue", time_phrase="last quarter"
)
COUNT = intent(summary="Number of orders", metric="number_of_orders", time_phrase=None)
TEST_USERS = ("finance", "sales.europe", "operations")
AppFactory = Callable[..., FastAPI]


def seeded_sql(conn: psycopg.Connection, key: str) -> tuple[uuid.UUID, str]:
    row = conn.execute(
        "SELECT id, sql_text FROM app.verified_queries WHERE lineage_id = %s AND is_active",
        (lineage_for(key),),
    ).fetchone()
    assert row is not None, f"seeded example {key} missing; run the seed"
    return row[0], row[1]


@pytest.fixture
async def make_app(
    settings: Settings,
    seeded: SeedSummary,
    analytics_engine: AsyncEngine,
    owner_conn: psycopg.Connection,
) -> AsyncIterator[AppFactory]:
    """The API with a scripted LLM, the real read-only executor, the real audit tables and
    the verified library read from the database."""
    started = dt.datetime.now(dt.UTC)
    engine = create_app_engine(settings)
    sessions = create_session_factory(engine)

    def make(model: ScriptedModel) -> FastAPI:
        deps = dataclasses.replace(
            fake_deps(model, real_executor(analytics_engine)),
            audit=DatabaseAuditSink(sessions, model_name="scripted", trace_project="tests"),
            load_verified=database_verified_loader(app_role_conninfo(settings)),
        )
        return create_app(
            settings, agent_deps=deps, checkpointer=InMemorySaver(serde=checkpoint_serializer())
        )

    yield make
    await engine.dispose()
    owner_conn.execute(
        "DELETE FROM app.conversations WHERE created_at >= %s AND user_id IN "
        "(SELECT id FROM app.users WHERE username = ANY(%s))",
        (started, list(TEST_USERS)),
    )
    owner_conn.execute(
        "DELETE FROM app.eval_cases WHERE created_at >= %s AND case_key LIKE 'FB-%%'", (started,)
    )
    # Library rows created by tests; seeded lineages are put back to their seeded state.
    seeded_lineages = [
        lineage_for(ex)
        for ex in ("revenue-last-quarter", "top-products-by-revenue", "freight-share-of-revenue")
    ]
    owner_conn.execute(
        "DELETE FROM app.verified_queries WHERE created_at >= %s AND version > 1 "
        "OR (created_at >= %s AND NOT (lineage_id = ANY(%s)))",
        (started, started, seeded_lineages),
    )
    owner_conn.execute(
        "UPDATE app.verified_queries SET is_active = true "
        "WHERE version = 1 AND lineage_id = ANY(%s)",
        (seeded_lineages,),
    )
    owner_conn.execute("DELETE FROM app.audit_log WHERE occurred_at >= %s", (started,))


async def test_scenario_10_a_similar_question_uses_the_verified_example(
    make_app: AppFactory,
    settings: Settings,
    owner_conn: psycopg.Connection,
) -> None:
    example_id, example_sql = seeded_sql(owner_conn, "revenue-last-quarter")
    model = ScriptedModel(
        REVENUE_Q1,
        sql=[sql_reply(example_sql, ["orders", "order_details"], metrics_used=["revenue"])],
    )
    async with running(make_app(model)) as client:
        headers = await login(client, settings, "finance")
        response = await client.post(
            "/ask",
            json={"question": "What was the total revenue in the last quarter?"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        correlation_id = assert_correlated(response)
    assert body["status"] == "ANSWERED"
    # The example reached the SQL prompt as few-shot guidance ...
    prompt = " ".join(str(m.content) for m in model.calls_by_kind["sql"][0])
    assert "What was our total revenue last quarter?" in prompt
    # ... and the audit records which example was used.
    used = owner_conn.execute(
        "SELECT g.verified_query_ids FROM app.generated_queries g "
        "JOIN app.agent_runs r ON r.id = g.run_id WHERE r.correlation_id = %s",
        (correlation_id,),
    ).fetchone()
    assert used is not None
    assert example_id in used[0]
    # Correct result: the same total as the owner computes directly.
    expected = owner_conn.execute(
        "SELECT SUM(od.unit_price * od.quantity * (1 - od.discount)) FROM public.orders o "
        "JOIN public.order_details od ON od.order_id = o.order_id "
        "WHERE o.order_date BETWEEN '2025-01-01' AND '2025-03-31'"
    ).fetchone()
    assert expected is not None
    assert round(Decimal(str(body["table"]["rows"][0][0])), 2) == round(Decimal(expected[0]), 2)


async def test_examples_respect_roles_and_disabling(
    make_app: AppFactory,
    settings: Settings,
    owner_conn: psycopg.Connection,
) -> None:
    finance_only_id, _ = seeded_sql(owner_conn, "freight-share-of-revenue")
    question = "Freight cost as a share of revenue by month in 2024"
    model = ScriptedModel(
        intent(summary=question, metric="revenue", time_phrase="2024"),
        sql=[sql_reply("SELECT count(*) AS orders FROM orders o", ["orders"])],
    )
    async with running(make_app(model)) as client:
        sales = await login(client, settings, "sales.europe")
        await client.post("/ask", json={"question": question}, headers=sales)
        sales_prompt = " ".join(str(m.content) for m in model.calls_by_kind["sql"][-1])
        assert "freight_share_pct" not in sales_prompt

        admin = await login(client, settings, "admin")
        disabled = await client.patch(
            f"/admin/verified-queries/{finance_only_id}", json={"is_active": False}, headers=admin
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["is_active"] is False

        finance = await login(client, settings, "finance")
        await client.post("/ask", json={"question": question}, headers=finance)
        finance_prompt = " ".join(str(m.content) for m in model.calls_by_kind["sql"][-1])
        assert "freight_share_pct" not in finance_prompt

        enabled = await client.patch(
            f"/admin/verified-queries/{finance_only_id}", json={"is_active": True}, headers=admin
        )
        assert enabled.json()["is_active"] is True
        await client.post("/ask", json={"question": question}, headers=finance)
        finance_prompt = " ".join(str(m.content) for m in model.calls_by_kind["sql"][-1])
        assert "freight_share_pct" in finance_prompt


async def test_scenario_11_a_not_helpful_answer_becomes_an_eval_case(
    make_app: AppFactory,
    settings: Settings,
    owner_conn: psycopg.Connection,
) -> None:
    async with running(make_app(ScriptedModel(COUNT))) as client:
        finance = await login(client, settings, "finance")
        asked = (
            await client.post(
                "/ask", json={"question": "How many orders are there?"}, headers=finance
            )
        ).json()
        rated = await client.post(
            "/feedback",
            headers=finance,
            json={
                "question_id": asked["question_id"],
                "rating": "not_helpful",
                "comment": "I wanted only shipped orders.",
            },
        )
        feedback_id = rated.json()["feedback_id"]
        run = owner_conn.execute(
            "SELECT run_id FROM app.feedback WHERE id = %s", (feedback_id,)
        ).fetchone()
        assert run is not None
        assert run[0] is not None  # linked to the question and its run

        admin = await login(client, settings, "admin")
        review = await client.get(
            "/admin/review", params={"kind": "not_helpful", "page_size": 100}, headers=admin
        )
        assert review.status_code == 200
        assert_correlated(review)
        mine = [i for i in review.json()["items"] if i["id"] == str(feedback_id)]
        assert mine, "the not-helpful answer is in the review list"
        assert mine[0]["detail"] == "I wanted only shipped orders."
        assert mine[0]["sql_text"].lower().startswith("select")

        case = await client.post(
            f"/admin/feedback/{feedback_id}/eval-case",
            headers=admin,
            json={
                "case_type": "medium",
                "expected_behaviour": "correct_result",
                "expected_sql": (
                    "SELECT count(*) AS orders FROM orders o WHERE o.shipped_date IS NOT NULL"
                ),
            },
        )
        assert case.status_code == 201, case.text
        assert case.json()["case_key"] == f"FB-{feedback_id}"
        again = await client.post(
            f"/admin/feedback/{feedback_id}/eval-case",
            headers=admin,
            json={"case_type": "medium", "expected_behaviour": "clarify"},
        )
        assert_error(again, 409, "CONFLICT")
        bad_sql = await client.post(
            f"/admin/feedback/{feedback_id + 10_000_000}/eval-case",
            headers=admin,
            json={"case_type": "medium", "expected_behaviour": "clarify"},
        )
        assert_error(bad_sql, 404, "NOT_FOUND")

        after = await client.get(
            "/admin/review", params={"kind": "not_helpful", "page_size": 100}, headers=admin
        )
        assert all(i["id"] != str(feedback_id) for i in after.json()["items"])

    row = owner_conn.execute(
        "SELECT c.test_username, c.question, c.expected_behaviour, c.source_feedback_id, "
        "f.review_status, d.name FROM app.eval_cases c "
        "JOIN app.feedback f ON f.id = c.source_feedback_id "
        "JOIN app.eval_datasets d ON d.id = c.dataset_id WHERE c.source_feedback_id = %s",
        (feedback_id,),
    ).fetchone()
    assert row == (
        "finance",
        "How many orders are there?",
        "correct_result",
        feedback_id,
        "converted",
        "review-cases",
    )


async def test_admin_verifies_and_corrects_a_query_as_new_versions(
    make_app: AppFactory,
    settings: Settings,
    owner_conn: psycopg.Connection,
) -> None:
    sql = (
        "SELECT s.company_name AS shipper, COUNT(DISTINCT o.order_id) AS number_of_orders "
        "FROM orders o JOIN shippers s ON s.shipper_id = o.ship_via "
        "WHERE o.order_date BETWEEN '2024-01-01' AND '2024-12-31' GROUP BY s.company_name"
    )
    base: dict[str, Any] = {
        "question_text": "Number of orders per shipper in 2024",
        "sql_text": sql,
        "description": "Orders per shipper for 2024.",
        "allowed_roles": ["finance_analyst", "operations_manager"],
        "metrics_used": ["number_of_orders"],
    }
    async with running(make_app(ScriptedModel(COUNT))) as client:
        admin = await login(client, settings, "admin")
        created = await client.post("/admin/verified-queries", json=base, headers=admin)
        assert created.status_code == 201, created.text
        first = created.json()
        assert first["version"] == 1
        assert sorted(first["tables_used"]) == ["orders", "shippers"]
        assert first["verified_by"] == "admin"

        corrected = await client.post(
            "/admin/verified-queries",
            headers=admin,
            json={
                **base,
                "sql_text": sql + " ORDER BY number_of_orders DESC",
                "lineage_id": first["lineage_id"],
            },
        )
        assert corrected.status_code == 201, corrected.text
        assert corrected.json()["version"] == 2
        versions = owner_conn.execute(
            "SELECT version, is_active FROM app.verified_queries WHERE lineage_id = %s "
            "ORDER BY version",
            (first["lineage_id"],),
        ).fetchall()
        assert versions == [(1, False), (2, True)]

        unsafe = await client.post(
            "/admin/verified-queries",
            headers=admin,
            json={**base, "sql_text": "DELETE FROM orders WHERE true"},
        )
        assert_error(unsafe, 400, "SQL_INVALID")
        wider = await client.post(
            "/admin/verified-queries",
            headers=admin,
            json={**base, "allowed_roles": ["operations_manager"], "metrics_used": ["revenue"]},
        )
        assert_error(wider, 400, "VALIDATION_ERROR")
        listing = await client.get(
            "/admin/verified-queries", params={"is_active": True, "page_size": 100}, headers=admin
        )
        assert listing.json()["total"] >= 16
        assert any(i["id"] == corrected.json()["id"] for i in listing.json()["items"])

        events = owner_conn.execute(
            "SELECT event_type FROM app.audit_log WHERE target_type = 'verified_query' "
            "AND target_id = ANY(%s) ORDER BY id",
            ([first["id"], corrected.json()["id"]],),
        ).fetchall()
        assert [e[0] for e in events] == ["verified_query_created", "verified_query_corrected"]
