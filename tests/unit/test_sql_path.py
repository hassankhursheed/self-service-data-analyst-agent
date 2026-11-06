"""Step 13: context, SQL generation, validation, execution and repair (LLM and DB mocked)."""

import pytest
from tests.fakes import ONE_ROW, FakeExecutor, ScriptedModel, fake_deps, intent, sql_reply

from app.agent.graph import Agent
from app.agent.nodes.n09_repair import REPAIR_LIMIT_MESSAGE
from app.agent.state import AgentRequest, AgentState
from app.core.enums import BlockReason, NodeName, QuestionStatus, RegionCode, RoleName
from app.core.errors import DbTimeout
from app.db.analytics import ReadonlyQueryError

S = QuestionStatus
ORDERS_2024 = intent(summary="Number of orders in 2024", metric="number_of_orders")
GOOD_SQL = sql_reply(
    "SELECT count(*) AS orders FROM orders o WHERE o.order_date BETWEEN '2024-01-01' AND '2024-12-31'",  # noqa: E501
    ["orders"],
    metrics_used=["number_of_orders"],
    date_range={"from": "2024-01-01", "to": "2024-12-31"},
)
# Passes validation but fails in the database (sum of a text column).
BAD_SQL = sql_reply("SELECT sum(o.ship_country) AS orders FROM orders o", ["orders"])
DB_ERROR = ReadonlyQueryError("db_error", "function sum(character varying) does not exist")


def request(
    question: str = "How many orders were placed in 2024?",
    role: RoleName = RoleName.FINANCE_ANALYST,
    region: RegionCode | None = None,
) -> AgentRequest:
    return AgentRequest(username="u", role=role, region=region, is_active=True, question=question)


async def run(
    model: ScriptedModel, executor: FakeExecutor, req: AgentRequest | None = None
) -> AgentState:
    return await Agent(fake_deps(model, executor)).run(req or request())


def path(state: AgentState) -> list[str]:
    return [s.node.value for s in state.steps]


# --- happy path ------------------------------------------------------------------------------


async def test_validated_sql_runs_with_the_users_context_and_a_limit() -> None:
    executor = FakeExecutor(ONE_ROW)
    state = await run(ScriptedModel(ORDERS_2024, sql=[GOOD_SQL]), executor)
    assert state.status is S.ANSWERED
    assert path(state) == ["N-01", "N-02", "N-03", "N-05", "N-06", "N-07", "N-08", "N-10", "N-11"]
    sql, user = executor.calls[0]
    assert state.validation is not None
    assert sql == state.validation.final_sql
    assert sql.endswith("LIMIT 200")
    assert user.role is RoleName.FINANCE_ANALYST
    assert state.execution == ONE_ROW
    assert state.context is not None
    assert "orders" in state.context.table_names
    assert state.low_confidence is False
    assert state.verified_examples == []  # hook for Step 20


async def test_sql_prompt_has_schema_and_period_but_no_hidden_columns() -> None:
    model = ScriptedModel(intent(summary="List customers", metric=None, time_phrase=None), sql=[
        sql_reply("SELECT company_name FROM customers", ["customers"])
    ])  # fmt: skip
    await run(
        model, FakeExecutor(), request("List our customers", role=RoleName.OPERATIONS_MANAGER)
    )
    prompt = " ".join(str(m.content) for m in model.calls_by_kind["sql"][0])
    assert "company_name" in prompt
    assert "contact_name" not in prompt
    assert "phone" not in prompt


async def test_sql_prompt_contains_the_resolved_period() -> None:
    model = ScriptedModel(intent(time_phrase="last quarter"), sql=[GOOD_SQL])
    await run(model, FakeExecutor())
    prompt = " ".join(str(m.content) for m in model.calls_by_kind["sql"][0])
    assert "Last quarter = 1 Jan to 31 Mar 2025" in prompt
    assert "from 2025-01-01 to 2025-03-31" in prompt


# --- blocked ---------------------------------------------------------------------------------


async def test_delete_request_is_blocked_and_nothing_is_executed() -> None:
    executor = FakeExecutor()
    model = ScriptedModel(ORDERS_2024)
    state = await run(model, executor, request("Delete all orders from 2024"))
    assert (state.status, state.block_reason) == (S.BLOCKED, BlockReason.WRITE_REQUEST)
    assert executor.calls == []
    assert model.calls_by_kind["sql"] == []


async def test_delete_sql_from_the_llm_is_blocked_by_validation() -> None:
    executor = FakeExecutor()
    model = ScriptedModel(ORDERS_2024, sql=[sql_reply("DELETE FROM orders", ["orders"])])
    state = await run(model, executor)
    assert (state.status, state.block_reason) == (S.BLOCKED, BlockReason.WRITE_STATEMENT)
    assert executor.calls == []
    assert state.blocked is not None
    assert state.blocked.sql == "DELETE FROM orders"
    assert state.user_message is not None
    assert "only reads data" in state.user_message


async def test_multi_statement_query_from_the_llm_is_rejected() -> None:
    executor = FakeExecutor()
    sql = "SELECT count(*) FROM orders; DROP TABLE orders"
    state = await run(ScriptedModel(ORDERS_2024, sql=[sql_reply(sql, ["orders"])]), executor)
    assert (state.status, state.block_reason) == (S.BLOCKED, BlockReason.MULTIPLE_STATEMENTS)
    assert executor.calls == []


async def test_hidden_column_is_blocked_for_a_role_without_access() -> None:
    executor = FakeExecutor()
    model = ScriptedModel(
        intent(summary="List customers", metric=None, time_phrase=None),
        sql=[sql_reply("SELECT contact_name FROM customers", ["customers"])],
    )
    state = await run(model, executor, request("List our customers", RoleName.OPERATIONS_MANAGER))
    assert (state.status, state.block_reason) == (S.BLOCKED, BlockReason.COLUMN_NOT_ALLOWED)
    assert executor.calls == []


async def test_question_with_no_usable_data_is_blocked_at_context() -> None:
    model = ScriptedModel(intent(summary="general mood", metric=None, time_phrase=None))
    state = await run(model, FakeExecutor(), request("How are things going?"))
    assert (state.status, state.block_reason) == (S.BLOCKED, BlockReason.NO_ALLOWED_DATA)
    assert path(state)[-2:] == ["N-05", "N-11"]


async def test_database_refusal_ends_blocked() -> None:
    executor = FakeExecutor(ReadonlyQueryError("permission_denied", "permission denied"))
    state = await run(ScriptedModel(ORDERS_2024, sql=[GOOD_SQL]), executor)
    assert (state.status, state.block_reason) == (S.BLOCKED, BlockReason.DATABASE_REFUSED)


# --- repair ----------------------------------------------------------------------------------


async def test_first_sql_fails_and_the_repair_succeeds() -> None:
    executor = FakeExecutor(DB_ERROR, ONE_ROW)
    model = ScriptedModel(ORDERS_2024, sql=[BAD_SQL], repair=[GOOD_SQL])
    state = await run(model, executor)
    assert state.status is S.ANSWERED
    assert state.repair_attempts == 1
    assert path(state) == [
        "N-01", "N-02", "N-03", "N-05", "N-06", "N-07", "N-08", "N-09", "N-07", "N-08", "N-10", "N-11"  # noqa: E501
    ]  # fmt: skip
    repair_step = next(s for s in state.steps if s.node is NodeName.REPAIR)
    assert (repair_step.from_status, repair_step.to_status) == (S.EXECUTION_FAILED, S.SQL_GENERATED)
    prompt = " ".join(str(m.content) for m in model.calls_by_kind["repair"][0])
    assert "function sum(character varying) does not exist" in prompt
    assert "SUM(o.ship_country) AS orders FROM orders AS o LIMIT 200" in prompt  # the SQL that ran


async def test_three_failures_end_failed_with_a_helpful_message() -> None:
    executor = FakeExecutor(DB_ERROR)
    model = ScriptedModel(ORDERS_2024, sql=[BAD_SQL], repair=[BAD_SQL])
    state = await run(model, executor)
    assert state.status is S.FAILED
    assert len(executor.calls) == 3
    assert len(model.calls_by_kind["repair"]) == 2
    assert state.repair_attempts == 2
    assert state.user_message == REPAIR_LIMIT_MESSAGE
    assert state.error is not None
    assert state.error.code == "REPAIR_LIMIT_REACHED"


async def test_repaired_sql_is_validated_again() -> None:
    executor = FakeExecutor(DB_ERROR, ONE_ROW)
    model = ScriptedModel(
        ORDERS_2024, sql=[BAD_SQL], repair=[sql_reply("DROP TABLE orders", ["orders"])]
    )
    state = await run(model, executor)
    assert (state.status, state.block_reason) == (S.BLOCKED, BlockReason.DDL_STATEMENT)
    assert len(executor.calls) == 1


async def test_query_timeout_gives_a_clear_message_and_no_repair() -> None:
    executor = FakeExecutor(ReadonlyQueryError("timeout", "canceling statement due to timeout"))
    model = ScriptedModel(ORDERS_2024, sql=[GOOD_SQL])
    state = await run(model, executor)
    assert state.status is S.FAILED
    assert state.user_message == DbTimeout.user_message
    assert state.error is not None
    assert state.error.code == "DB_TIMEOUT"
    assert model.calls_by_kind["repair"] == []


async def test_unreachable_database_is_retried_then_succeeds() -> None:
    executor = FakeExecutor(ConnectionRefusedError("db down"), ONE_ROW)
    state = await run(ScriptedModel(ORDERS_2024, sql=[GOOD_SQL]), executor)
    assert state.status is S.ANSWERED
    assert len(executor.calls) == 2


async def test_unreachable_database_fails_without_crashing() -> None:
    executor = FakeExecutor(ConnectionRefusedError("db down"))
    state = await run(ScriptedModel(ORDERS_2024, sql=[GOOD_SQL]), executor)
    assert state.status is S.FAILED
    assert state.error is not None
    assert state.error.retryable is True


# --- structured output -----------------------------------------------------------------------


async def test_malformed_sql_output_is_regenerated_once() -> None:
    model = ScriptedModel(ORDERS_2024, sql=["here is your query: SELECT 1", GOOD_SQL])
    state = await run(model, FakeExecutor())
    assert state.status is S.ANSWERED
    assert len(model.calls_by_kind["sql"]) == 2


async def test_malformed_sql_output_twice_ends_with_could_not_answer() -> None:
    model = ScriptedModel(ORDERS_2024, sql=['{"sql": ""}', "nope"])
    executor = FakeExecutor()
    state = await run(model, executor)
    assert state.status is S.FAILED
    assert state.error is not None
    assert (state.error.code, state.error.node) == ("MALFORMED_OUTPUT", NodeName.SQL_GENERATION)
    assert executor.calls == []


async def test_tables_outside_the_context_count_as_malformed() -> None:
    outside = sql_reply("SELECT count(*) FROM territories", ["territories"])
    model = ScriptedModel(ORDERS_2024, sql=[outside, GOOD_SQL])
    state = await run(model, FakeExecutor())
    assert state.status is S.ANSWERED
    retry_prompt = str(model.calls_by_kind["sql"][1][-1].content)
    assert "outside the allowed context" in retry_prompt


@pytest.mark.parametrize(
    ("reply", "low"),
    [
        (GOOD_SQL, False),
        ({**GOOD_SQL, "confidence": "low"}, True),
        ({**GOOD_SQL, "date_range": {"from": "2023-01-01", "to": "2023-12-31"}}, True),
    ],
)
async def test_low_confidence_is_flagged(reply: dict[str, object], low: bool) -> None:
    state = await run(ScriptedModel(ORDERS_2024, sql=[reply]), FakeExecutor())
    assert state.low_confidence is low


async def test_sales_manager_query_runs_with_their_region() -> None:
    executor = FakeExecutor()
    req = request(role=RoleName.SALES_MANAGER, region=RegionCode.AMERICAS)
    await run(ScriptedModel(ORDERS_2024, sql=[GOOD_SQL]), executor, req)
    _, user = executor.calls[0]
    assert (user.role, user.region) == (RoleName.SALES_MANAGER, RegionCode.AMERICAS)
