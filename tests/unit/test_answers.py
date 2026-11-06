"""Step 14: grounded answers, chart rules and the response model (LLM and DB mocked)."""

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest

from app.agent.charts import ChartConfig, choose_chart
from app.agent.config import load_agent_config
from app.agent.graph import Agent
from app.agent.grounding import check_grounding, context_numbers, extract_numbers
from app.agent.response import build_response
from app.agent.state import AgentRequest, AgentState
from app.core.enums import QuestionStatus, RoleName
from app.core.errors import RetryableError
from app.db.analytics import QueryResult
from tests.fakes import FakeExecutor, ScriptedModel, fake_deps, intent, sql_reply

S = QuestionStatus
CHART = load_agent_config().answer.chart
CATEGORIES = [
    "Beverages",
    "Condiments",
    "Confections",
    "Dairy",
    "Grains",
    "Meat",
    "Produce",
    "Seafood",
]
BY_CATEGORY = QueryResult(
    columns=["category_name", "revenue"],
    rows=[(c, Decimal(10000 + i * 1111.11)) for i, c in enumerate(CATEGORIES)],
    row_count=8,
    truncated=False,
)
REVENUE_SQL = sql_reply(
    "SELECT c.category_name, SUM(od.unit_price * od.quantity) AS revenue FROM orders o "
    "JOIN order_details od ON od.order_id = o.order_id JOIN products p ON p.product_id = "
    "od.product_id JOIN categories c ON c.category_id = p.category_id GROUP BY 1",
    ["orders", "order_details", "products", "categories"],
    metrics_used=["revenue"],
)
REVENUE_INTENT = intent(summary="Revenue by category in 2024", grouping="category")


def chart(columns: list[str], rows: Sequence[tuple[Any, ...]], truncated: bool = False) -> str:
    return choose_chart(columns, list(rows), truncated=truncated, config=CHART).type


# --- chart rules (pure) -----------------------------------------------------------------------


def test_single_value_is_a_metric_card() -> None:
    assert chart(["revenue"], [(Decimal("1234.5"),)]) == "metric_card"


def test_time_series_is_a_line_chart() -> None:
    rows = [(dt.date(2024, m, 1), Decimal(m * 100)) for m in range(1, 13)]
    spec = choose_chart(["month", "revenue"], rows, truncated=False, config=CHART)
    assert (spec.type, spec.x, spec.y) == ("line", "month", ["revenue"])
    assert spec.data[0] == {"month": "2024-01-01", "revenue": 100.0}


def test_time_column_detected_by_name() -> None:
    rows = [("2024-01", 5), ("2024-02", 7), ("2024-03", 6)]
    assert chart(["order_month", "orders"], rows) == "line"


def test_numeric_year_column_is_the_x_axis() -> None:
    rows = [(2023, Decimal(5)), (2024, Decimal(9))]
    spec = choose_chart(["year", "revenue"], rows, truncated=False, config=CHART)
    assert (spec.type, spec.x, spec.y) == ("line", "year", ["revenue"])


def test_category_comparison_is_a_bar_chart() -> None:
    spec = choose_chart(BY_CATEGORY.columns, BY_CATEGORY.rows, truncated=False, config=CHART)
    assert (spec.type, spec.x, spec.y, len(spec.data)) == ("bar", "category_name", ["revenue"], 8)


def test_series_are_capped() -> None:
    rows = [("A", 1, 2, 3, 4, 5), ("B", 2, 3, 4, 5, 6)]
    spec = choose_chart(["name", "a", "b", "c", "d", "e"], rows, truncated=False, config=CHART)
    assert spec.type == "bar"
    assert len(spec.y) == CHART.max_series


@pytest.mark.parametrize(
    ("columns", "rows", "truncated"),
    [
        (["name", "revenue"], [], False),
        (["name", "revenue"], [("A", 1), ("B", 2)], True),
        (["name", "revenue"], [(f"c{i}", i) for i in range(CHART.max_bars + 1)], False),
        (["company_name", "city"], [("A", "Berlin"), ("B", "Paris")], False),
        (["day", "orders"], [(f"2024-01-{i:02d}", i) for i in range(1, 30)] * 20, False),
    ],
)
def test_unsuitable_results_get_no_chart(
    columns: list[str], rows: list[tuple[object, ...]], truncated: bool
) -> None:
    assert chart(columns, rows, truncated) == "none"


def test_chart_config_comes_from_the_agent_config() -> None:
    assert isinstance(CHART, ChartConfig)
    assert CHART.max_bars >= 2


# --- grounding (pure) -------------------------------------------------------------------------

ROWS = [("Beverages", Decimal("12345.678"), 40), ("Seafood", Decimal("8000.00"), 60)]
COLS = ["category_name", "revenue", "orders"]


def grounded(text: str, extra: set[float] | None = None) -> bool:
    return check_grounding(text, COLS, ROWS, context_numbers=extra).grounded


def test_extracts_formatted_numbers() -> None:
    values = [n.value for n in extract_numbers("1,234.5 and 12.3k, 2 million, 45% and -3")]
    assert values == [1234.5, 12300.0, 2_000_000.0, 45.0, -3.0]


def test_an_invented_number_fails_the_check() -> None:
    result = check_grounding("Beverages earned 99,999.", COLS, ROWS)
    assert result.grounded is False
    assert result.ungrounded == ["99,999"]


@pytest.mark.parametrize(
    "text",
    [
        "Beverages earned 12,345.68.",
        "Beverages earned about 12,346.",
        "Beverages earned 12.3k.",
        "Seafood had 60 orders.",
        "Beverages had 40% of the orders.",  # share of the column total (40 / 100)
        "Seafood had 50% more orders than Beverages.",  # change between two values
    ],
)
def test_rounded_and_derived_numbers_are_grounded(text: str) -> None:
    assert grounded(text), text


def test_dates_and_counts_from_the_context_are_allowed() -> None:
    allowed = context_numbers("2024 = 1 Jan to 31 Dec 2024", extra=[2, 5])
    assert grounded("In 2024 the top 2 categories were Beverages and Seafood.", allowed)
    assert not grounded("In 2024 Beverages earned 77.", allowed)


def test_an_invented_percentage_fails() -> None:
    assert not grounded("Beverages grew 13% this year.")


# --- N-10 in the graph -------------------------------------------------------------------------


def request(question: str = "What was revenue by category in 2024?") -> AgentRequest:
    return AgentRequest(
        username="finance", role=RoleName.FINANCE_ANALYST, is_active=True, question=question
    )


async def run(model: ScriptedModel, result: QueryResult = BY_CATEGORY) -> AgentState:
    return await Agent(fake_deps(model, FakeExecutor(result))).run(request())


GOOD = {
    "explanation": "Seafood led with 17,777.77.",
    "sql_description": "Sums revenue by category.",
}
INVENTED = {"explanation": "Revenue was 1,000,000.", "sql_description": "Sums revenue."}


async def test_a_grounded_llm_answer_is_used() -> None:
    state = await run(ScriptedModel(REVENUE_INTENT, sql=[REVENUE_SQL], answer=[GOOD]))
    assert state.status is S.ANSWERED
    assert state.answer is not None
    assert (state.answer.source, state.answer.text) == ("llm", GOOD["explanation"])
    assert state.answer.chart.type == "bar"


async def test_an_ungrounded_answer_is_regenerated_once() -> None:
    model = ScriptedModel(REVENUE_INTENT, sql=[REVENUE_SQL], answer=[INVENTED, GOOD])
    state = await run(model)
    assert state.answer is not None
    assert state.answer.source == "llm"
    assert len(model.calls_by_kind["answer"]) == 2
    assert "1,000,000" in str(model.calls_by_kind["answer"][1][-1].content)


async def test_ungrounded_twice_falls_back_to_a_template_from_the_rows() -> None:
    model = ScriptedModel(REVENUE_INTENT, sql=[REVENUE_SQL], answer=[INVENTED])
    state = await run(model)
    assert state.status is S.ANSWERED
    assert state.answer is not None
    assert state.answer.source == "template"
    assert "1,000,000" not in state.answer.text
    assert "Beverages" in state.answer.text
    assert check_grounding(state.answer.text, BY_CATEGORY.columns, BY_CATEGORY.rows,
                           context_numbers={8.0, 3.0, 2024.0, 1.0, 31.0}).grounded  # fmt: skip


async def test_llm_failure_at_the_answer_still_answers_from_the_rows() -> None:
    model = ScriptedModel(
        REVENUE_INTENT, sql=[REVENUE_SQL], answer=[RetryableError("provider down")]
    )
    state = await run(model)
    assert state.status is S.ANSWERED
    assert state.answer is not None
    assert state.answer.source == "template"


async def test_the_llm_sees_only_the_top_rows() -> None:
    many = QueryResult(
        columns=["category_name", "revenue"],
        rows=[(f"Category {i}", Decimal(i)) for i in range(60)],
        row_count=60,
        truncated=False,
    )
    model = ScriptedModel(REVENUE_INTENT, sql=[REVENUE_SQL], answer=[GOOD])
    await run(model, many)
    prompt = " ".join(str(m.content) for m in model.calls_by_kind["answer"][0])
    assert "Category 19 | 19" in prompt
    assert "Category 20 |" not in prompt
    assert "first 20" in prompt


async def test_empty_result_gets_an_honest_message_and_no_llm_call() -> None:
    empty = QueryResult(columns=["category_name", "revenue"], rows=[], row_count=0, truncated=False)
    model = ScriptedModel(REVENUE_INTENT, sql=[REVENUE_SQL], answer=[GOOD])
    state = await run(model, empty)
    assert state.status is S.ANSWERED
    assert state.answer is not None
    assert state.answer.source == "empty"
    assert state.answer.text.startswith(
        "No orders matched these filters (2024 = 1 Jan to 31 Dec 2024)."
    )
    assert "broader question" in state.answer.text
    assert state.answer.chart.type == "none"
    assert model.calls_by_kind["answer"] == []


# --- response model ------------------------------------------------------------------------


async def test_response_always_has_sql_description_assumptions_date_range_and_row_count() -> None:
    model = ScriptedModel(
        intent(summary="Revenue by category", grouping="category", time_phrase=None,
               missing=[{"part": "time_range", "reason": "no period"}]),
        sql=[REVENUE_SQL], answer=[GOOD],
    )  # fmt: skip
    state = await Agent(fake_deps(model, FakeExecutor(BY_CATEGORY))).run(
        request("What was revenue by category?")
    )
    response = build_response(state)
    assert response.status is S.ANSWERED
    assert response.answer == GOOD["explanation"]
    assert response.sql.text is not None
    assert response.sql.text.endswith("LIMIT 200")
    assert response.sql.description == GOOD["sql_description"]
    assert response.assumptions
    assert response.date_range is not None
    assert response.date_range.label == "This year = 1 Jan to 6 May 2025"
    assert response.row_count == 8
    assert response.chart is not None
    assert response.chart.type == "bar"
    assert response.table is not None
    assert response.table.rows[0] == ["Beverages", 10000.0]
    assert response.correlation_id is not None


async def test_low_confidence_is_labelled_in_the_response() -> None:
    model = ScriptedModel(REVENUE_INTENT, sql=[{**REVENUE_SQL, "confidence": "low"}], answer=[GOOD])
    state = await run(model)
    response = build_response(state)
    assert response.low_confidence is True
    assert response.low_confidence_label is not None
    assert response.low_confidence_label.startswith("Low confidence")


async def test_large_results_are_paginated() -> None:
    many = QueryResult(
        columns=["category_name", "revenue"],
        rows=[(f"C{i}", Decimal(i)) for i in range(120)],
        row_count=120,
        truncated=False,
    )
    state = await run(ScriptedModel(REVENUE_INTENT, sql=[REVENUE_SQL], answer=[GOOD]), many)
    page = build_response(state, page=2, page_size=50).table
    assert page is not None
    assert (page.page, page.total_pages, page.total_rows, len(page.rows)) == (2, 3, 120, 50)
    assert page.rows[0][0] == "C50"
    last = build_response(state, page=9, page_size=50).table
    assert last is not None
    assert (last.page, len(last.rows)) == (3, 20)


async def test_blocked_response_carries_the_reason() -> None:
    state = await Agent(fake_deps(ScriptedModel(REVENUE_INTENT))).run(
        request("Delete all orders from 2024")
    )
    response = build_response(state)
    assert response.status is S.BLOCKED
    assert response.block is not None
    assert response.block.message
    assert response.answer is None
