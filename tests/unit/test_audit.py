"""Step 16 unit tests: N-11, masking and the per-attempt records (no database)."""

import dataclasses

import pytest

from app.agent.audit import MemoryAuditSink, input_snapshot, prompt_version_text
from app.agent.graph import Agent
from app.agent.state import AgentRequest
from app.core.enums import ExecutionStatus, QueryKind, QuestionStatus, RoleName
from app.core.masking import mask_text, mask_value
from app.db.analytics import ReadonlyQueryError
from tests.fakes import ONE_ROW, FakeExecutor, ScriptedModel, fake_deps, intent, sql_reply

S = QuestionStatus
SECRET_EMAIL = "jane.doe@example.com"
SECRET_PHONE = "+44 20 7946 0958"


def request(question: str = "How many orders were placed in 2024?") -> AgentRequest:
    return AgentRequest(
        username="finance", role=RoleName.FINANCE_ANALYST, is_active=True, question=question
    )


@pytest.mark.parametrize(
    ("text", "hidden"),
    [
        ("mail jane.doe@example.com now", SECRET_EMAIL),
        ("call +44 20 7946 0958", "7946 0958"),
        ("call (171) 555-2222", "555-2222"),
        ("card 4111 1111 1111 1111", "4111 1111"),
        ("password=hunter2", "hunter2"),
        ("postgresql://app_rw:s3cret@db:5432/x", "s3cret"),
        ("token sk-ant-abcdefghijklmnop123", "abcdefghijklmnop"),
    ],
)
def test_sensitive_values_are_masked(text: str, hidden: str) -> None:
    assert hidden not in mask_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "revenue 12,345.67 in 2024",
        "BETWEEN '2025-01-01' AND '2025-05-06'",
        "order 10248 and orders 10248 - 10250",
        "top 5 products in Q1 2025",
    ],
)
def test_business_values_are_kept(text: str) -> None:
    assert mask_text(text) == text


def test_mask_value_walks_nested_data() -> None:
    masked = mask_value({"a": [SECRET_EMAIL, {"b": SECRET_PHONE}], "n": 3})
    assert SECRET_EMAIL not in str(masked)
    assert masked["n"] == 3


async def test_audit_sink_receives_the_final_state() -> None:
    sink = MemoryAuditSink()
    deps = dataclasses.replace(fake_deps(ScriptedModel(intent())), audit=sink)
    state = await Agent(deps).run(request())
    assert state.audit_ok is True
    assert len(sink.records) == 1
    recorded = sink.records[0]
    assert recorded.status is S.ANSWERED
    assert recorded.correlation_id == state.correlation_id


async def test_a_failing_audit_write_never_breaks_the_answer() -> None:
    deps = dataclasses.replace(fake_deps(ScriptedModel(intent())), audit=MemoryAuditSink(fail=True))
    state = await Agent(deps).run(request())
    assert state.status is S.ANSWERED
    assert state.audit_ok is False
    assert state.answer is not None


async def test_sensitive_values_never_reach_the_llm_or_the_state() -> None:
    model = ScriptedModel(intent())
    state = await Agent(fake_deps(model)).run(
        request(f"How many orders in 2024? Reply to {SECRET_EMAIL} or {SECRET_PHONE}")
    )
    prompts = " ".join(
        str(m.content) for calls in model.calls_by_kind.values() for c in calls for m in c
    )
    assert SECRET_EMAIL not in prompts
    assert "7946 0958" not in prompts
    assert SECRET_EMAIL not in state.request.question
    assert "[MASKED_EMAIL]" in state.question


async def test_correlation_id_is_also_the_trace_run_id() -> None:
    state = await Agent(fake_deps(ScriptedModel(intent()))).run(request())
    assert state.correlation_id is not None
    assert state.request.correlation_id == state.correlation_id


async def test_every_sql_attempt_and_execution_is_recorded() -> None:
    bad = sql_reply("SELECT sum(o.ship_country) AS x FROM orders o", ["orders"])
    good = sql_reply("SELECT count(*) AS orders FROM orders o", ["orders"])
    executor = FakeExecutor(
        ReadonlyQueryError("db_error", "function sum(text) does not exist"), ONE_ROW
    )
    state = await Agent(fake_deps(ScriptedModel(intent(), sql=[bad], repair=[good]), executor)).run(
        request()
    )
    assert [(a.attempt, a.kind) for a in state.sql_attempts] == [
        (1, QueryKind.INITIAL),
        (2, QueryKind.REPAIR),
    ]
    assert [(e.attempt, e.status) for e in state.executions] == [
        (1, ExecutionStatus.DB_ERROR),
        (2, ExecutionStatus.SUCCESS),
    ]
    assert state.executions[1].row_count == 1
    assert state.executions[1].view_schema == "finance_ro"


async def test_input_snapshot_can_rerun_and_is_masked() -> None:
    state = await Agent(fake_deps(ScriptedModel(intent()))).run(
        request(f"Orders in 2024 for {SECRET_EMAIL}")
    )
    snapshot = input_snapshot(state)
    assert snapshot["request"]["role"] == "finance_analyst"
    assert SECRET_EMAIL not in str(snapshot)
    assert "system@v1" in prompt_version_text(state)


async def test_guardrail_block_has_a_blocked_record() -> None:
    state = await Agent(fake_deps(ScriptedModel(intent()))).run(request("Drop the customers table"))
    assert state.status is S.BLOCKED
    assert state.blocked is not None
    assert state.blocked.stage.value == "input_guardrail"
