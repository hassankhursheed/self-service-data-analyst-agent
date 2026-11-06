"""The answer as the API and UI receive it, built from the final agent state.

For an ANSWERED question it always contains the answer text, the chart spec, a page of the
result table, the row count, the SQL that ran, a one-line description of it, the
assumptions, the resolved date range and, when needed, the low-confidence label.
"""

import datetime as dt
import math
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.agent.charts import ChartSpec, json_value
from app.agent.state import AgentState
from app.core.enums import BlockReason, QuestionStatus


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class TablePage(_Frozen):
    columns: list[str]
    rows: list[list[Any]]
    page: int
    page_size: int
    total_rows: int
    total_pages: int
    truncated: bool


class SqlInfo(_Frozen):
    text: str | None
    description: str | None


class DateRangeInfo(_Frozen):
    from_date: dt.date
    to_date: dt.date
    label: str


class ClarificationInfo(_Frozen):
    question: str
    options: list[str]


class BlockInfo(_Frozen):
    reason_code: BlockReason
    message: str


class AgentResponse(_Frozen):
    correlation_id: uuid.UUID | None
    thread_id: str | None
    status: QuestionStatus | None
    message: str | None
    answer: str | None = None
    low_confidence: bool = False
    low_confidence_label: str | None = None
    chart: ChartSpec | None = None
    table: TablePage | None = None
    row_count: int = 0
    sql: SqlInfo = SqlInfo(text=None, description=None)
    assumptions: list[str] = []
    date_range: DateRangeInfo | None = None
    notices: list[str] = []
    interpreted_as: str | None = None
    clarification: ClarificationInfo | None = None
    block: BlockInfo | None = None


def table_page(state: AgentState, page: int, page_size: int) -> TablePage | None:
    result = state.execution
    if result is None:
        return None
    total_pages = max(1, math.ceil(result.row_count / page_size))
    page = min(max(page, 1), total_pages)
    start = (page - 1) * page_size
    rows = [[json_value(v) for v in row] for row in result.rows[start : start + page_size]]
    return TablePage(
        columns=result.columns,
        rows=rows,
        page=page,
        page_size=page_size,
        total_rows=result.row_count,
        total_pages=total_pages,
        truncated=result.truncated,
    )


def build_response(state: AgentState, *, page: int = 1, page_size: int = 50) -> AgentResponse:
    answer = state.answer
    date_range = (
        DateRangeInfo(
            from_date=state.date_range.from_date,
            to_date=state.date_range.to_date,
            label=state.date_range.label,
        )
        if state.date_range
        else None
    )
    clarification = (
        ClarificationInfo(
            question=state.pending_clarification.question,
            options=list(state.pending_clarification.options),
        )
        if state.awaiting_reply and state.pending_clarification
        else None
    )
    block = (
        BlockInfo(reason_code=state.block_reason, message=state.user_message or "")
        if state.block_reason and state.status in {QuestionStatus.BLOCKED, QuestionStatus.REJECTED}
        else None
    )
    return AgentResponse(
        correlation_id=state.correlation_id,
        thread_id=state.thread_id,
        status=state.status,
        message=state.user_message,
        answer=answer.text if answer else None,
        low_confidence=state.low_confidence,
        low_confidence_label=answer.low_confidence_label if answer else None,
        chart=answer.chart if answer else None,
        table=table_page(state, page, page_size),
        row_count=state.execution.row_count if state.execution else 0,
        sql=SqlInfo(
            text=state.executed_sql,
            description=answer.sql_description if answer else None,
        ),
        assumptions=list(state.assumptions),
        date_range=date_range,
        notices=list(state.notices),
        interpreted_as=state.interpreted_question,
        clarification=clarification,
        block=block,
    )
