"""Step 15: follow-ups with the PostgreSQL checkpointer, user-scoped threads, app tables."""

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.conversations import (
    AuthenticatedUser,
    ConversationNotFound,
    ConversationService,
    thread_id_for,
)
from app.agent.graph import Agent
from app.agent.memory import postgres_checkpointer
from app.core.config import Settings
from app.core.enums import QuestionStatus, RegionCode, RoleName
from app.db.session import create_app_engine, create_session_factory
from scripts.seed import SeedSummary
from tests.fakes import ScriptedModel, fake_deps, intent, sql_reply
from tests.integration.test_sql_path_db import real_executor

pytestmark = pytest.mark.integration
S = QuestionStatus

TOP5_SQL = (
    "SELECT p.product_name, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue "
    "FROM orders o JOIN order_details od ON od.order_id = o.order_id "
    "JOIN products p ON p.product_id = od.product_id "
    "{join}WHERE o.order_date BETWEEN '2025-01-01' AND '2025-05-06'{filter} "
    "GROUP BY p.product_name ORDER BY revenue DESC LIMIT 5"
)
TOP5_TABLES = ["orders", "order_details", "products"]


def top5(country: str | None = None) -> str:
    if country is None:
        return TOP5_SQL.format(join="", filter="")
    return TOP5_SQL.format(
        join="JOIN customers c ON c.customer_id = o.customer_id ",
        filter=f" AND c.country = '{country}'",
    )


def user_row(conn: psycopg.Connection, username: str) -> AuthenticatedUser:
    row = conn.execute(
        "SELECT u.id, r.name, ur.region_code FROM app.users u "
        "JOIN app.user_roles uro ON uro.user_id = u.id JOIN app.roles r ON r.id = uro.role_id "
        "LEFT JOIN app.user_regions ur ON ur.user_id = u.id WHERE u.username = %s",
        (username,),
    ).fetchone()
    assert row is not None
    region = RegionCode(row[2]) if row[2] else None
    return AuthenticatedUser(
        user_id=row[0], username=username, role=RoleName(row[1]), region=region
    )


@pytest.fixture
async def service_factory(
    settings: Settings, seeded: SeedSummary, analytics_engine: AsyncEngine,
    owner_conn: psycopg.Connection,
) -> AsyncIterator[object]:  # fmt: skip
    app_engine = create_app_engine(settings)
    sessions = create_session_factory(app_engine)
    created: list[ConversationService] = []

    async with postgres_checkpointer(settings) as checkpointer:

        def make(model: ScriptedModel) -> ConversationService:
            agent = Agent(fake_deps(model, real_executor(analytics_engine)), checkpointer)
            service = ConversationService(agent, sessions)
            created.append(service)
            return service

        yield make
    await app_engine.dispose()
    # Remove what the tests created (test users only).
    owner_conn.execute(
        "DELETE FROM app.conversations WHERE user_id IN (SELECT id FROM app.users "
        "WHERE username IN ('finance', 'operations', 'sales.americas'))"
    )
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
        owner_conn.execute(f"DELETE FROM checkpoints.{table} WHERE thread_id LIKE 'user:%'")  # noqa: S608


async def test_follow_up_now_only_for_germany_gives_the_filtered_result(
    service_factory: object, owner_conn: psycopg.Connection
) -> None:
    model = ScriptedModel(
        intent(summary="Top 5 products by revenue in 2025", time_phrase="2025", top_n=5,
               grouping="product"),
        intent(summary="Top 5 products by revenue in 2025 for customers in Germany",
               is_follow_up=True,
               standalone_question="Top 5 products by revenue in 2025 for customers in Germany",
               time_phrase="2025", top_n=5, grouping="product", entities=["Germany"]),
        sql=[sql_reply(top5(), TOP5_TABLES, metrics_used=["revenue"]),
             sql_reply(top5("Germany"), [*TOP5_TABLES, "customers"], metrics_used=["revenue"])],
    )  # fmt: skip
    service: ConversationService = service_factory(model)  # type: ignore[operator]
    finance = user_row(owner_conn, "finance")

    first = await service.ask(finance, "Top 5 products by revenue in 2025")
    assert first.status is S.ANSWERED, (first.block_reason, first.blocked)
    conversation_id = first.request.conversation_id
    assert conversation_id is not None

    second = await service.ask(finance, "now only for Germany", conversation_id)
    assert second.status is S.ANSWERED, (second.block_reason, second.blocked)
    assert (
        second.interpreted_question == "Top 5 products by revenue in 2025 for customers in Germany"
    )
    assert (
        "Interpreted as: Top 5 products by revenue in 2025 for customers in Germany"
        in second.notices
    )
    # The second analysis saw the first question as history.
    history_prompt = " ".join(str(m.content) for m in model.calls[1])
    assert "1. Top 5 products by revenue in 2025" in history_prompt
    # Correct, filtered rows.
    expected = owner_conn.execute(
        "SELECT p.product_name, SUM(od.unit_price * od.quantity * (1 - od.discount)) "
        "FROM public.orders o JOIN public.order_details od USING (order_id) "
        "JOIN public.products p USING (product_id) JOIN public.customers c USING (customer_id) "
        "WHERE o.order_date BETWEEN '2025-01-01' AND '2025-05-06' AND c.country = 'Germany' "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
    ).fetchall()
    assert second.execution is not None
    assert [(r[0], round(Decimal(r[1]), 2)) for r in second.execution.rows] == [
        (r[0], round(Decimal(r[1]), 2)) for r in expected
    ]
    # Both questions are stored, linked to the conversation.
    detail = await service.open_conversation(finance, conversation_id)
    assert [q.question for q in detail.questions] == [
        "Top 5 products by revenue in 2025",
        "now only for Germany",
    ]
    assert {q.status for q in detail.questions} == {"ANSWERED"}
    # Conversation state lives in the PostgreSQL checkpointer.
    thread = thread_id_for(finance.user_id, conversation_id)
    stored = owner_conn.execute(
        "SELECT count(*) FROM checkpoints.checkpoints WHERE thread_id = %s", (thread,)
    ).fetchone()
    assert stored is not None
    assert stored[0] > 0


async def test_follow_up_trying_another_region_still_returns_only_americas(
    service_factory: object, owner_conn: psycopg.Connection
) -> None:
    by_country = (
        "SELECT c.country, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue "
        "FROM orders o JOIN order_details od ON od.order_id = o.order_id "
        "JOIN customers c ON c.customer_id = o.customer_id {where}GROUP BY c.country"
    )
    tables = ["orders", "order_details", "customers"]
    model = ScriptedModel(
        intent(summary="Revenue by country", grouping="country", time_phrase=None),
        intent(summary="Revenue for Germany", is_follow_up=True,
               standalone_question="Revenue by country for Germany", time_phrase=None,
               entities=["Germany"]),
        sql=[sql_reply(by_country.format(where=""), tables, metrics_used=["revenue"]),
             sql_reply(by_country.format(where="WHERE c.country = 'Germany' "), tables,
                       metrics_used=["revenue"])],
    )  # fmt: skip
    service: ConversationService = service_factory(model)  # type: ignore[operator]
    americas = user_row(owner_conn, "sales.americas")

    first = await service.ask(americas, "Revenue by country")
    assert first.execution is not None
    assert {r[0] for r in first.execution.rows} <= {"USA", "Canada", "Mexico"}
    assert first.request.conversation_id is not None

    second = await service.ask(americas, "now only for Germany", first.request.conversation_id)
    assert second.status is S.ANSWERED
    assert second.execution is not None
    assert second.execution.rows == []  # Germany is not in the Americas region
    assert second.answer is not None
    assert second.answer.text.startswith("No orders matched these filters")


async def test_user_a_cannot_open_user_bs_conversation(
    service_factory: object, owner_conn: psycopg.Connection
) -> None:
    model = ScriptedModel(intent(summary="Number of orders", metric="number_of_orders",
                                 time_phrase=None))  # fmt: skip
    service: ConversationService = service_factory(model)  # type: ignore[operator]
    finance = user_row(owner_conn, "finance")
    operations = user_row(owner_conn, "operations")

    state = await service.ask(finance, "How many orders are there?")
    conversation_id = state.request.conversation_id
    assert conversation_id is not None

    with pytest.raises(ConversationNotFound):
        await service.open_conversation(operations, conversation_id)
    with pytest.raises(ConversationNotFound):
        await service.ask(operations, "and by month?", conversation_id)
    with pytest.raises(ConversationNotFound):
        await service.clarify(operations, conversation_id, "By revenue")
    assert all(c.id != conversation_id for c in await service.list_conversations(operations))
    assert any(c.id == conversation_id for c in await service.list_conversations(finance))
    assert thread_id_for(finance.user_id, conversation_id) != thread_id_for(
        operations.user_id, conversation_id
    )
    with pytest.raises(ConversationNotFound):
        await service.open_conversation(finance, uuid.uuid4())


async def test_a_new_conversation_does_not_carry_earlier_context(
    service_factory: object, owner_conn: psycopg.Connection
) -> None:
    model = ScriptedModel(intent(summary="Number of orders", metric="number_of_orders",
                                 time_phrase=None))  # fmt: skip
    service: ConversationService = service_factory(model)  # type: ignore[operator]
    finance = user_row(owner_conn, "finance")

    first = await service.ask(finance, "How many orders are there?")
    second = await service.ask(finance, "now only for Germany")  # new conversation
    assert first.request.conversation_id != second.request.conversation_id
    assert second.history == []
    prompt = " ".join(str(m.content) for m in model.calls[1])
    assert "none (this is the first question)" in prompt
    assert second.interpreted_question is None
