"""Step 16: every final status produces complete, linked, masked audit records."""

import dataclasses
import datetime as dt
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.audit import DatabaseAuditSink
from app.agent.graph import Agent
from app.agent.state import AgentRequest, AgentState
from app.core.config import Settings
from app.core.enums import QuestionStatus, RoleName
from app.db.session import create_app_engine, create_session_factory
from scripts.seed import SeedSummary
from tests.fakes import ScriptedModel, fake_deps, intent, sql_reply
from tests.integration.test_sql_path_db import real_executor

pytestmark = pytest.mark.integration
S = QuestionStatus
SECRET_EMAIL = "audit.secret.person@example.com"
SECRET_PHONE = "+44 20 7946 0958"


def user_id(conn: psycopg.Connection, username: str) -> uuid.UUID:
    row = conn.execute("SELECT id FROM app.users WHERE username = %s", (username,)).fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


@pytest.fixture
async def ask(
    settings: Settings, seeded: SeedSummary, analytics_engine: AsyncEngine,
    owner_conn: psycopg.Connection,
) -> AsyncIterator[Callable[..., Awaitable[AgentState]]]:  # fmt: skip
    engine = create_app_engine(settings)
    sink = DatabaseAuditSink(
        create_session_factory(engine), model_name="test-model", trace_project="test-project"
    )
    started = dt.datetime.now(dt.UTC)

    async def run(
        model: ScriptedModel, question: str, username: str = "finance",
        role: RoleName | None = RoleName.FINANCE_ANALYST,
    ) -> AgentState:  # fmt: skip
        deps = dataclasses.replace(fake_deps(model, real_executor(analytics_engine)), audit=sink)
        request = AgentRequest(
            username=username, role=role, is_active=True, question=question,
            user_id=user_id(owner_conn, username),
        )  # fmt: skip
        state = await Agent(deps).run(request)
        assert state.audit_ok is True
        return state

    yield run
    await engine.dispose()
    owner_conn.execute("DELETE FROM app.conversations WHERE created_at >= %s", (started,))
    owner_conn.execute("DELETE FROM app.audit_log WHERE occurred_at >= %s", (started,))
    owner_conn.execute("DELETE FROM app.agent_errors WHERE created_at >= %s", (started,))


def count(conn: psycopg.Connection, sql: str, *params: object) -> int:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return int(row[0])


def run_of(conn: psycopg.Connection, state: AgentState) -> tuple[uuid.UUID, str, int]:
    row = conn.execute(
        "SELECT r.id, r.final_status, (SELECT count(*) FROM app.agent_steps s WHERE s.run_id = r.id) "  # noqa: E501
        "FROM app.agent_runs r WHERE r.correlation_id = %s",
        (state.correlation_id,),
    ).fetchone()
    assert row is not None, "no agent_runs row"
    return uuid.UUID(str(row[0])), str(row[1]), int(row[2])


REVENUE_SQL = sql_reply(
    "SELECT count(*) AS orders FROM orders o WHERE o.order_date BETWEEN '2024-01-01' AND "
    "'2024-12-31'",
    ["orders"],
)


async def test_answered_question_has_complete_linked_records(
    ask: Callable[..., Awaitable[AgentState]], owner_conn: psycopg.Connection
) -> None:
    state: AgentState = await ask(
        ScriptedModel(intent(), sql=[REVENUE_SQL]), "How many orders in 2024?"
    )
    assert state.status is S.ANSWERED
    run_id, final, steps = run_of(owner_conn, state)
    assert final == "ANSWERED"
    assert steps == len(state.steps)  # one row per node, N-11 included
    row = owner_conn.execute(
        "SELECT model_name, prompt_version, graph_version, input_tokens, output_tokens, "
        "estimated_cost_usd, langsmith_trace_url, total_latency_ms FROM app.agent_runs WHERE id = %s",  # noqa: E501
        (run_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "test-model"
    assert "intent@" in row[1]
    assert row[2] == state.graph_version
    assert (row[3], row[4]) == (state.usage.input_tokens, state.usage.output_tokens)
    assert str(state.correlation_id) in row[6]
    assert row[7] >= 0
    question = owner_conn.execute(
        "SELECT status, role_name, resolved_date_from, completed_at FROM app.questions "
        "WHERE correlation_id = %s", (state.correlation_id,),
    ).fetchone()  # fmt: skip
    assert question is not None
    assert (question[0], question[1], str(question[2])) == (
        "ANSWERED",
        "finance_analyst",
        "2024-01-01",
    )
    assert question[3] is not None
    assert (
        count(owner_conn, "SELECT count(*) FROM app.generated_queries WHERE run_id = %s", run_id)
        == 1
    )
    execution = owner_conn.execute(
        "SELECT e.status, e.row_count, e.db_role FROM app.query_executions e "
        "JOIN app.generated_queries g ON g.id = e.generated_query_id WHERE g.run_id = %s",
        (run_id,),
    ).fetchone()
    assert execution == ("success", 1, "analytics_ro/finance_ro")
    assert count(
        owner_conn,
        "SELECT count(*) FROM app.audit_log WHERE correlation_id = %s AND event_type = 'question_answered'",  # noqa: E501
        state.correlation_id,
    ) == 1  # fmt: skip
    assert (
        count(
            owner_conn,
            "SELECT count(*) FROM app.agent_errors WHERE correlation_id = %s",
            state.correlation_id,
        )
        == 0
    )
    nodes = [r[0] for r in owner_conn.execute(
        "SELECT node_name FROM app.agent_steps WHERE run_id = %s ORDER BY seq", (run_id,)
    ).fetchall()]  # fmt: skip
    assert nodes[0] == "N-01"
    assert nodes[-1] == "N-11"


async def test_blocked_question_records_the_block_reason(
    ask: Callable[..., Awaitable[AgentState]], owner_conn: psycopg.Connection
) -> None:
    model = ScriptedModel(intent(), sql=[sql_reply("DELETE FROM orders", ["orders"])])
    state: AgentState = await ask(model, "How many orders in 2024?")
    assert state.status is S.BLOCKED
    run_id, final, _ = run_of(owner_conn, state)
    assert final == "BLOCKED"
    blocked = owner_conn.execute(
        "SELECT b.stage, b.reason_code, b.generated_query_id IS NOT NULL FROM app.blocked_queries b "  # noqa: E501
        "WHERE b.run_id = %s",
        (run_id,),
    ).fetchone()
    assert blocked == ("sql_validation", "WRITE_STATEMENT", True)
    assert count(
        owner_conn,
        "SELECT count(*) FROM app.query_executions e JOIN app.generated_queries g "
        "ON g.id = e.generated_query_id WHERE g.run_id = %s",
        run_id,
    ) == 0  # fmt: skip


async def test_rejected_question_is_recorded(
    ask: Callable[..., Awaitable[AgentState]], owner_conn: psycopg.Connection
) -> None:
    state: AgentState = await ask(ScriptedModel(intent()), "How many orders?", "no.role", None)
    assert state.status is S.REJECTED
    run_id, final, steps = run_of(owner_conn, state)
    assert (final, steps) == ("REJECTED", 2)  # N-01 and N-11
    status = owner_conn.execute(
        "SELECT status FROM app.questions WHERE correlation_id = %s", (state.correlation_id,)
    ).fetchone()
    assert status == ("REJECTED",)
    assert (
        count(owner_conn, "SELECT count(*) FROM app.generated_queries WHERE run_id = %s", run_id)
        == 0
    )


async def test_failed_question_has_an_error_record_with_rerunnable_input(
    ask: Callable[..., Awaitable[AgentState]], owner_conn: psycopg.Connection
) -> None:
    broken = sql_reply("SELECT sum(o.ship_country) AS x FROM orders o", ["orders"])
    model = ScriptedModel(intent(), sql=[broken], repair=[broken])
    state: AgentState = await ask(model, "How many orders in 2024?")
    assert state.status is S.FAILED
    run_id, final, _ = run_of(owner_conn, state)
    assert final == "FAILED"
    assert (
        count(owner_conn, "SELECT count(*) FROM app.generated_queries WHERE run_id = %s", run_id)
        == 3
    )
    assert count(
        owner_conn,
        "SELECT count(*) FROM app.query_executions e JOIN app.generated_queries g "
        "ON g.id = e.generated_query_id WHERE g.run_id = %s AND e.status = 'db_error'",
        run_id,
    ) == 3  # fmt: skip
    error = owner_conn.execute(
        "SELECT node_name, error_type, input_snapshot, run_id FROM app.agent_errors "
        "WHERE correlation_id = %s",
        (state.correlation_id,),
    ).fetchone()
    assert error is not None
    assert (error[0], error[1]) == ("N-09", "REPAIR_LIMIT_REACHED")
    assert error[2]["request"]["question"] == "How many orders in 2024?"
    assert error[2]["request"]["role"] == "finance_analyst"
    assert uuid.UUID(str(error[3])) == run_id


async def test_clarifications_are_stored(
    settings: Settings, seeded: SeedSummary, analytics_engine: AsyncEngine,
    owner_conn: psycopg.Connection,
) -> None:  # fmt: skip
    engine = create_app_engine(settings)
    sink = DatabaseAuditSink(create_session_factory(engine), model_name="m", trace_project="p")
    ambiguous = intent(
        summary="Top customers", metric=None, time_phrase=None, grouping="customer",
        missing=[{"part": "metric"}], clarifying_question="By revenue or number of orders?",
        options=["By revenue", "By number of orders"],
    )  # fmt: skip
    clear = intent(summary="Top customers by revenue in 2024", grouping="customer")
    deps = dataclasses.replace(
        fake_deps(ScriptedModel(ambiguous, clear), real_executor(analytics_engine)), audit=sink
    )
    agent = Agent(deps)
    paused = await agent.run(AgentRequest(
        username="finance", role=RoleName.FINANCE_ANALYST, is_active=True,
        question="Top customers", user_id=user_id(owner_conn, "finance"),
    ))  # fmt: skip
    assert paused.thread_id is not None
    state = await agent.resume(paused.thread_id, "By revenue")
    try:
        rows = owner_conn.execute(
            "SELECT c.asked_text, c.answer_text FROM app.clarifications c JOIN app.questions q "
            "ON q.id = c.question_id WHERE q.correlation_id = %s",
            (state.correlation_id,),
        ).fetchall()
        assert rows == [("By revenue or number of orders?", "By revenue")]
    finally:
        owner_conn.execute(
            "DELETE FROM app.conversations WHERE id IN (SELECT conversation_id FROM app.questions "
            "WHERE correlation_id = %s)",
            (state.correlation_id,),
        )
        await engine.dispose()


async def test_correlation_id_links_every_related_row(
    ask: Callable[..., Awaitable[AgentState]], owner_conn: psycopg.Connection
) -> None:
    state: AgentState = await ask(
        ScriptedModel(intent(), sql=[REVENUE_SQL]), "How many orders in 2024?"
    )
    cid = state.correlation_id
    linked = owner_conn.execute(
        "SELECT "
        " (SELECT count(*) FROM app.questions WHERE correlation_id = %(c)s),"
        " (SELECT count(*) FROM app.agent_runs WHERE correlation_id = %(c)s),"
        " (SELECT count(*) FROM app.audit_log WHERE correlation_id = %(c)s),"
        " (SELECT count(*) FROM app.agent_steps s JOIN app.agent_runs r ON r.id = s.run_id"
        "   WHERE r.correlation_id = %(c)s),"
        " (SELECT count(*) FROM app.generated_queries g JOIN app.agent_runs r ON r.id = g.run_id"
        "   WHERE r.correlation_id = %(c)s)",
        {"c": cid},
    ).fetchone()
    assert linked is not None
    assert linked[:3] == (1, 1, 1)
    assert linked[3] == len(state.steps)
    assert linked[4] == 1


AUDIT_TABLES = [
    "questions", "conversations", "agent_runs", "agent_steps", "generated_queries",
    "query_executions", "blocked_queries", "clarifications", "audit_log", "agent_errors",
]  # fmt: skip


async def test_masked_values_never_appear_in_the_audit_tables(
    ask: Callable[..., Awaitable[AgentState]], owner_conn: psycopg.Connection
) -> None:
    question = f"How many orders in 2024? Send it to {SECRET_EMAIL} or call {SECRET_PHONE}"
    broken = sql_reply("SELECT sum(o.ship_country) AS x FROM orders o", ["orders"])
    await ask(ScriptedModel(intent(), sql=[broken], repair=[broken]), question)  # FAILED path
    await ask(ScriptedModel(intent(), sql=[REVENUE_SQL]), question)  # ANSWERED path
    for table in AUDIT_TABLES:
        hits = count(
            owner_conn,
            f"SELECT count(*) FROM app.{table} t WHERE row_to_json(t)::text LIKE %s "  # noqa: S608
            "OR row_to_json(t)::text LIKE %s",
            f"%{SECRET_EMAIL}%",
            "%7946 0958%",
        )
        assert hits == 0, table
    masked = count(
        owner_conn,
        "SELECT count(*) FROM app.questions WHERE question_text LIKE %s",
        "%[MASKED_EMAIL]%",
    )
    assert masked >= 2
