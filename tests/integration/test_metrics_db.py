"""Step 21: monitoring metrics over the audit tables (real database).

Known runs are inserted on days far in the future (2030) so real activity never mixes in;
each metric must return exactly the expected number.
"""

import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal

import psycopg
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.checkpoint import checkpoint_serializer
from app.api.main import create_app
from app.core.config import MonitoringConfig, Settings
from app.db.session import create_app_engine, create_session_factory
from app.services.metrics import InvalidPeriod, Metrics, MetricsService, p95
from scripts.seed import SeedSummary
from tests.fakes import ScriptedModel, fake_deps
from tests.integration.test_api import assert_correlated, assert_error, login, running

pytestmark = pytest.mark.integration
DAY = dt.date(2030, 1, 15)
P95_DAY = dt.date(2030, 2, 1)
MARK = "metrics-test"
UTC = dt.UTC


def at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


class Seeder:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self.users: dict[str, uuid.UUID] = dict(
            conn.execute(
                "SELECT username, id FROM app.users WHERE username IN ('finance', 'sales.europe')"
            ).fetchall()
        )
        self.conversation = conn.execute(
            "INSERT INTO app.conversations (user_id, title) VALUES (%s, %s) RETURNING id",
            (self.users["finance"], MARK),
        ).fetchone()[0]  # type: ignore[index]

    def question(
        self, username: str, role: str | None, when: dt.datetime, status: str = "RECEIVED"
    ) -> uuid.UUID:
        row = self.conn.execute(
            "INSERT INTO app.questions (correlation_id, conversation_id, user_id, question_text, "
            "role_name, status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (uuid.uuid4(), self.conversation, self.users[username], MARK, role, status, when),
        ).fetchone()
        assert row is not None
        return uuid.UUID(str(row[0]))

    def run(
        self,
        question: uuid.UUID,
        number: int,
        status: str,
        when: dt.datetime,
        latency: int,
        tokens: tuple[int, int] = (0, 0),
        cost: str = "0",
    ) -> uuid.UUID:
        row = self.conn.execute(
            "INSERT INTO app.agent_runs (question_id, run_number, correlation_id, graph_version, "
            "prompt_version, semantic_version, model_name, final_status, total_latency_ms, "
            "input_tokens, output_tokens, estimated_cost_usd, started_at, finished_at) "
            "VALUES (%s, %s, %s, 'test', 'test', '1', 'test', %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (
                question,
                number,
                uuid.uuid4(),
                status,
                latency,
                tokens[0],
                tokens[1],
                Decimal(cost),
                when,
                when + dt.timedelta(milliseconds=latency),
            ),
        ).fetchone()
        assert row is not None
        # As the conversation service does when a question finishes.
        self.conn.execute("UPDATE app.questions SET status = %s WHERE id = %s", (status, question))
        return uuid.UUID(str(row[0]))

    def queries(self, run: uuid.UUID, kinds: list[str]) -> None:
        for attempt, kind in enumerate(kinds, start=1):
            self.conn.execute(
                "INSERT INTO app.generated_queries (run_id, attempt, kind, sql_text) "
                "VALUES (%s, %s, %s, 'SELECT 1')",
                (run, attempt, kind),
            )


@pytest.fixture
def seeded_runs(owner_conn: psycopg.Connection, seeded: SeedSummary) -> Iterator[Seeder]:
    # Remove what an interrupted earlier run may have left behind.
    owner_conn.execute("DELETE FROM app.conversations WHERE title = %s", (MARK,))
    owner_conn.execute("DELETE FROM app.audit_log WHERE details->>'test' = %s", (MARK,))
    s = Seeder(owner_conn)
    # Q1 finance: answered at once.
    q1 = s.question("finance", "finance_analyst", at(DAY, 9))
    r = s.run(q1, 1, "ANSWERED", at(DAY, 9), 100, (100, 20), "0.0010")
    s.queries(r, ["initial"])
    # Q2 finance: one clarification, then answered after one repair (one run: runs are
    # written when a question finishes).
    q2 = s.question("finance", "finance_analyst", at(DAY, 10))
    owner_conn.execute(
        "INSERT INTO app.clarifications (question_id, asked_text, created_at) VALUES (%s, %s, %s)",
        (q2, "By revenue or orders?", at(DAY, 10, 1)),
    )
    r = s.run(q2, 1, "ANSWERED", at(DAY, 10, 5), 300, (150, 30), "0.0015")
    s.queries(r, ["initial", "repair"])
    # Q3 sales: blocked by the validator.
    q3 = s.question("sales.europe", "sales_manager", at(DAY, 11))
    r = s.run(q3, 1, "BLOCKED", at(DAY, 11), 400)
    owner_conn.execute(
        "INSERT INTO app.blocked_queries (run_id, stage, reason_code, reason_text, created_at) "
        "VALUES (%s, 'sql_validation', 'WRITE_STATEMENT', 'Only read-only questions.', %s)",
        (r, at(DAY, 11)),
    )
    # Q4 sales: failed after two repairs.
    q4 = s.question("sales.europe", "sales_manager", at(DAY, 12))
    r = s.run(q4, 1, "FAILED", at(DAY, 12), 500, (200, 40), "0.0020")
    s.queries(r, ["initial", "repair", "repair"])
    # Q5 no role: rejected (next day, still inside the two-day period).
    q5 = s.question("finance", None, at(DAY + dt.timedelta(days=1), 8))
    s.run(q5, 1, "REJECTED", at(DAY + dt.timedelta(days=1), 8), 600)
    # Outside the period: must not count.
    q6 = s.question("finance", "finance_analyst", at(DAY + dt.timedelta(days=2), 8))
    s.run(q6, 1, "ANSWERED", at(DAY + dt.timedelta(days=2), 8), 9999, (999, 999), "9")
    # Ratings and failed logins.
    for question, rating in ((q1, "helpful"), (q2, "helpful"), (q4, "not_helpful")):
        owner_conn.execute(
            "INSERT INTO app.feedback (question_id, user_id, rating, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (question, s.users["finance"], rating, at(DAY, 13), at(DAY, 13)),
        )
    for when in (at(DAY, 7), at(DAY, 7, 1), at(DAY + dt.timedelta(days=3), 7)):
        owner_conn.execute(
            "INSERT INTO app.audit_log (event_type, occurred_at, details) "
            "VALUES ('login_failed', %s, %s)",
            (when, json.dumps({"reason": "wrong_password", "test": MARK})),
        )
    # p95 sample on its own day: latencies 10, 20, ..., 200 ms.
    for i in range(1, 21):
        q = s.question("finance", "finance_analyst", at(P95_DAY, 0, i))
        s.run(q, 1, "ANSWERED", at(P95_DAY, 0, i), 10 * i)
    yield s
    owner_conn.execute("DELETE FROM app.conversations WHERE id = %s", (s.conversation,))
    owner_conn.execute("DELETE FROM app.audit_log WHERE details->>'test' = %s", (MARK,))


@pytest.fixture
async def service(settings: Settings) -> AsyncIterator[MetricsService]:
    engine = create_app_engine(settings)
    yield MetricsService(create_session_factory(engine), MonitoringConfig(time_zone="UTC"))
    await engine.dispose()


async def period_metrics(service: MetricsService) -> Metrics:
    return await service.metrics(DAY, DAY + dt.timedelta(days=1))


async def test_each_metric_returns_the_expected_number(
    service: MetricsService,
    seeded_runs: Seeder,
) -> None:
    m = await period_metrics(service)
    assert m.questions == 5
    assert m.questions_by_role == {"finance_analyst": 2, "no_role": 1, "sales_manager": 2}
    assert m.outcomes.model_dump() == {
        "answered": 2,
        "blocked": 1,
        "rejected": 1,
        "failed": 1,
        "awaiting_clarification": 0,
        "in_progress": 0,
    }
    assert m.blocked_by_reason == {"WRITE_STATEMENT": 1}
    assert m.repair_attempts == 3
    assert m.repaired_runs == 2
    assert m.repair_success_rate == 0.5
    assert m.clarifications_asked == 1
    assert m.runs == 5
    assert m.latency_avg_ms == 380.0  # (100 + 300 + 400 + 500 + 600) / 5
    # Position 0.95 * 4 = 3.8: 500 + 0.8 * (600 - 500) = 580.
    assert m.latency_p95_ms == p95([100, 300, 400, 500, 600]) == 580.0
    assert (m.input_tokens, m.output_tokens) == (450, 90)
    assert m.cost_usd == Decimal("0.0045")
    assert m.feedback.model_dump() == {"helpful": 2, "not_helpful": 1}
    assert m.failed_logins == 2
    assert [p.date for p in m.daily] == [DAY, DAY + dt.timedelta(days=1)]
    assert [(p.questions, p.answered, p.blocked, p.failed, p.rejected) for p in m.daily] == [
        (4, 2, 1, 1, 0),
        (1, 0, 0, 0, 1),
    ]
    assert sum(p.cost_usd for p in m.daily) == m.cost_usd


async def test_a_paused_question_counts_as_awaiting_clarification(
    service: MetricsService, seeded_runs: Seeder
) -> None:
    m = await service.metrics(DAY, DAY)
    assert m.questions == 4
    seeded_runs.question("finance", "finance_analyst", at(DAY, 14), "CLARIFICATION_NEEDED")
    seeded_runs.question("finance", "finance_analyst", at(DAY, 15), "SQL_GENERATED")
    m = await service.metrics(DAY, DAY)
    assert m.questions == 6
    assert m.outcomes.awaiting_clarification == 1
    assert m.outcomes.in_progress == 1
    assert m.runs == 4  # paused and running questions have no run yet


async def test_p95_latency_on_a_known_sample(service: MetricsService, seeded_runs: Seeder) -> None:
    m = await service.metrics(P95_DAY, P95_DAY)
    sample = [10.0 * i for i in range(1, 21)]
    assert m.runs == 20
    # Position 0.95 * 19 = 18.05: 190 + 0.05 * (200 - 190) = 190.5 (linear interpolation).
    assert m.latency_p95_ms == 190.5
    assert p95(sample) == 190.5
    assert m.latency_avg_ms == 105.0


async def test_an_empty_period_and_invalid_periods(service: MetricsService) -> None:
    m = await service.metrics(dt.date(2031, 6, 1), dt.date(2031, 6, 3))
    assert (m.questions, m.runs, m.latency_p95_ms, m.repair_success_rate) == (0, 0, None, None)
    assert len(m.daily) == 3
    with pytest.raises(InvalidPeriod):
        await service.metrics(dt.date(2031, 6, 3), dt.date(2031, 6, 1))
    with pytest.raises(InvalidPeriod):
        await service.metrics(dt.date(2031, 1, 1), dt.date(2031, 12, 31))


async def test_the_metrics_endpoint_is_admin_only_and_correlated(
    settings: Settings,
    seeded_runs: Seeder,
) -> None:
    app = create_app(
        settings,
        agent_deps=fake_deps(ScriptedModel()),
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
    )
    async with running(app) as client:
        admin = await login(client, settings, "admin")
        response = await client.get(
            "/admin/metrics", params={"from": DAY.isoformat(), "to": "2030-01-16"}, headers=admin
        )
        assert response.status_code == 200, response.text
        assert_correlated(response)
        assert response.json()["questions"] == 5
        assert response.json()["latency_p95_ms"] == 580.0
        today = await client.get("/admin/metrics", headers=admin)
        assert today.status_code == 200
        assert today.json()["period_from"] == today.json()["period_to"]
        assert_error(
            await client.get(
                "/admin/metrics", headers=admin, params={"from": "2030-01-16", "to": "2030-01-15"}
            ),
            400,
            "VALIDATION_ERROR",
        )
        finance = await login(client, settings, "finance")
        assert_error(await client.get("/admin/metrics", headers=finance), 403, "ADMIN_ONLY")
