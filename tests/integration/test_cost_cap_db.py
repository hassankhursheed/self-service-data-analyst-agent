"""Step 25: the daily cost cap stops new questions once today's budget is used."""

import datetime as dt
import uuid
from collections.abc import Iterator
from decimal import Decimal

import psycopg
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.checkpoint import checkpoint_serializer
from app.api.main import create_app
from app.core.config import Settings
from app.db.session import create_app_engine, create_session_factory
from app.services.cost_cap import DailyCostCap
from scripts.seed import SeedSummary
from tests.fakes import ScriptedModel, fake_deps
from tests.integration.test_api import assert_error, login, running

pytestmark = pytest.mark.integration
MARK = "cost-cap-test"


@pytest.fixture
def expensive_run_today(owner_conn: psycopg.Connection, seeded: SeedSummary) -> Iterator[None]:
    user = owner_conn.execute("SELECT id FROM app.users WHERE username = 'finance'").fetchone()
    assert user is not None
    conversation = owner_conn.execute(
        "INSERT INTO app.conversations (user_id, title) VALUES (%s, %s) RETURNING id",
        (user[0], MARK),
    ).fetchone()
    assert conversation is not None
    question = owner_conn.execute(
        "INSERT INTO app.questions (correlation_id, conversation_id, user_id, question_text, "
        "status) VALUES (%s, %s, %s, %s, 'ANSWERED') RETURNING id",
        (uuid.uuid4(), conversation[0], user[0], MARK),
    ).fetchone()
    assert question is not None
    owner_conn.execute(
        "INSERT INTO app.agent_runs (question_id, run_number, correlation_id, graph_version, "
        "prompt_version, semantic_version, final_status, estimated_cost_usd, started_at) "
        "VALUES (%s, 1, %s, 't', 't', '1', 'ANSWERED', 1000, now())",
        (question[0], uuid.uuid4()),
    )
    yield
    owner_conn.execute("DELETE FROM app.conversations WHERE id = %s", (conversation[0],))


def with_cap(settings: Settings, cap: float) -> Settings:
    return settings.model_copy(
        update={"api": settings.api.model_copy(update={"daily_cost_cap_usd": cap})}
    )


async def test_questions_stop_when_the_daily_budget_is_used(
    settings: Settings, expensive_run_today: None
) -> None:
    model = ScriptedModel()
    app = create_app(
        with_cap(settings, 1.0),
        agent_deps=fake_deps(model),
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
    )
    async with running(app) as client:
        headers = await login(client, settings, "finance")
        refused = await client.post("/ask", json={"question": "How many orders?"}, headers=headers)
        body = assert_error(refused, 503, "DAILY_BUDGET_REACHED")
        assert "tomorrow" in body["error"]["message"]
        assert model.calls == []  # refused before any LLM call
        # The rest of the app keeps working.
        assert (await client.get("/conversations", headers=headers)).status_code == 200


async def test_a_zero_cap_turns_the_check_off(
    settings: Settings, expensive_run_today: None
) -> None:
    engine = create_app_engine(settings)
    try:
        off = DailyCostCap(create_session_factory(engine), 0)
        await off.check()  # no exception
        on = DailyCostCap(create_session_factory(engine), 1.0)
        assert await on.spent_today() >= Decimal("1000")
    finally:
        await engine.dispose()


async def test_the_daily_sum_is_cached_briefly(settings: Settings, seeded: SeedSummary) -> None:
    engine = create_app_engine(settings)
    now = [0.0]
    cap = DailyCostCap(create_session_factory(engine), 5.0, cache_seconds=10, clock=lambda: now[0])
    try:
        first = await cap.spent_today()
        cap._cached = (now[0], dt.datetime.now(dt.UTC).date(), Decimal("999"))
        assert await cap.spent_today() == Decimal("999")  # within the cache window
        now[0] = 11.0
        assert await cap.spent_today() == first  # re-read after the window
    finally:
        await engine.dispose()
