"""N-10 Answer and Visualization: grounded explanation, SQL description and chart.

- Empty result: an honest "No ... matched these filters" message and a suggestion; no LLM.
- Otherwise the LLM sees only the first ``rows_for_llm`` rows (role-allowed columns only)
  and returns structured JSON: a short summary, the listed rows as ``items`` (label, value,
  detail) and a one-line SQL description. The UI shows the summary, then the items as a
  ranked list (Step 26 review). Every item must exist in the result with the same value.
- Every number in the explanation must be grounded in the result (app/agent/grounding.py);
  one regeneration, then a plain template answer built from the rows. An unavailable LLM
  also falls back to the template, because the result itself is still correct.
"""

import re
from decimal import Decimal
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.charts import choose_chart, is_identifier
from app.agent.deps import AgentDeps, usage_of
from app.agent.grounding import check_grounding, context_numbers
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.nodes.sql_context import date_range_text
from app.agent.state import AgentState, Answer, AnswerItem
from app.core.enums import Confidence, NodeName, QuestionStatus, RegionCode
from app.core.errors import AppError
from app.core.llm import ainvoke_structured
from app.core.masking import mask_text
from app.core.prompts import load_prompt
from app.core.text import plain_text
from app.db.analytics import QueryResult
from app.db.setup.northwind_data import load_regions
from app.safety.access_policy import get_access_policy

_ENTITY_NAMES = {"order_details": "order lines"}


# A detail that is only an identifier ("product_id 29", "ID: 29") adds noise to the list.
_ID_DETAIL = re.compile(r"(^|[\s_])id\b", re.IGNORECASE)

MAX_ITEMS = 10


def _number(value: object) -> object:
    """'27,537.13' or '27537.13' -> 27537.13; anything else is left for validation."""
    if isinstance(value, str):
        cleaned = plain_text(value).replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return value
    return value


class DraftItem(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    label: str = Field(min_length=1, max_length=120)
    value: float | None = None
    detail: str | None = Field(default=None, max_length=160)

    @field_validator("label", "detail", mode="before")
    @classmethod
    def _plain(cls, value: object) -> object:
        return plain_text(value) if isinstance(value, str) else value

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value: object) -> object:
        return _number(value)


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    explanation: str = Field(min_length=1, max_length=1200)
    items: list[DraftItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    sql_description: str = Field(min_length=1, max_length=300)

    @field_validator("explanation", "sql_description", mode="before")
    @classmethod
    def _plain(cls, value: object) -> object:
        return plain_text(value) if isinstance(value, str) else value

    @field_validator("items", mode="before")
    @classmethod
    def _items(cls, value: object) -> object:
        return [] if value is None else value

    @model_validator(mode="before")
    @classmethod
    def _summary(cls, data: object) -> object:
        """Prompt v3 calls the text "summary"; earlier prompts called it "explanation"."""
        if isinstance(data, dict) and "summary" in data and "explanation" not in data:
            data = {**data, "explanation": data["summary"]}
            del data["summary"]
        return data


def format_value(value: Any) -> str:  # noqa: ANN401 (result cells have any SQL type)
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float | Decimal):
        return f"{float(value):,.2f}".rstrip("0").rstrip(".")
    return str(value)


def personal_columns() -> frozenset[str]:
    """Result columns whose values never reach the LLM (``llm_hidden_columns`` in
    config/access_policy.yaml): contact names, addresses, phone numbers and similar."""
    return frozenset(c.lower() for c in get_access_policy().llm_hidden_columns)


def rows_text(result: QueryResult, limit: int, hidden: frozenset[str] = frozenset()) -> str:
    """Top rows for the LLM (section 27): values of personal columns are replaced by
    [PERSONAL] and other personal values such as phone numbers are masked. The user still
    sees the full table if their role allows it."""
    hide = [column.lower() in hidden for column in result.columns]
    lines = [
        mask_text(
            " | ".join(
                "[PERSONAL]" if h else format_value(v) for v, h in zip(row, hide, strict=False)
            )
        )
        for row in result.rows[:limit]
    ]
    return "\n".join(lines)


def template_answer(result: QueryResult, period_label: str | None) -> str:
    """A plain answer built only from result values (used when the LLM cannot be trusted)."""
    period = f" for {period_label}" if period_label else ""
    if result.row_count == 1 and len(result.columns) <= 3:
        pairs = ", ".join(
            f"{c.replace('_', ' ')} = {format_value(v)}"
            for c, v in zip(result.columns, result.rows[0], strict=False)
        )
        return f"Result{period}: {pairs}."
    # Rows are shown as a ranked list and a table; the sentence only summarises (Step 26).
    more = (
        " (cut at the row limit; narrow the question to see everything)" if result.truncated else ""
    )
    return f"Here are the {result.row_count} results{period}{more}."


def _label_and_value_columns(result: QueryResult) -> tuple[int | None, int | None]:
    """The first text column and the first numeric column that are not IDs."""
    label = value = None
    for i, column in enumerate(result.columns):
        if is_identifier(column):
            continue
        cells = [row[i] for row in result.rows if row[i] is not None]
        if label is None and cells and all(isinstance(c, str) for c in cells):
            label = i
        if (
            value is None
            and cells
            and all(isinstance(c, int | float | Decimal) and not isinstance(c, bool) for c in cells)
        ):
            value = i
    return label, value


def items_from_rows(result: QueryResult, limit: int = MAX_ITEMS) -> list[AnswerItem]:
    """The list built straight from the result (used when the model gives none)."""
    if result.row_count < 2:
        return []
    label, value = _label_and_value_columns(result)
    if label is None:
        return []
    return [
        AnswerItem(
            label=str(row[label]),
            value=float(row[value]) if value is not None and row[value] is not None else None,
        )
        for row in result.rows[:limit]
    ]


def item_problems(items: list[DraftItem], result: QueryResult) -> list[str]:
    """Items whose label is not a result row, or whose value differs from that row."""
    problems: list[str] = []
    for item in items:
        wanted = item.label.strip().lower()

        def matches(row: tuple[Any, ...], *, names_only: bool, wanted: str = wanted) -> bool:
            return any(
                isinstance(c, str)
                and c.strip().lower() == wanted
                and not (names_only and is_identifier(col))
                for col, c in zip(result.columns, row, strict=False)
            )

        rows = [row for row in result.rows if matches(row, names_only=True)]
        if not rows:
            in_ids = any(matches(row, names_only=False) for row in result.rows)
            problems.append(
                f"{item.label!r} is an ID; use the row's name instead"
                if in_ids
                else f"{item.label!r} is not in the result"
            )
            continue
        if item.value is None:
            continue
        numbers = [
            float(c)
            for row in rows
            for c in row
            if isinstance(c, int | float | Decimal) and not isinstance(c, bool)
        ]
        if not any(abs(item.value - n) <= max(0.01, abs(n) * 0.005) for n in numbers):
            problems.append(f"{item.label!r} has value {item.value} which is not in its row")
    return problems


def template_description(state: AgentState) -> str:
    tables = state.generated.tables_used if state.generated else []
    names = ", ".join(_ENTITY_NAMES.get(t, t.replace("_", " ")) for t in tables) or "the data"
    period = f" for {state.date_range.label.split(' = ')[-1]}" if state.date_range else ""
    return f"Reads {names}{period}."


@lru_cache
def region_name(code: RegionCode) -> str:
    """Display name from config/regions.yaml ("Europe", "Rest of World")."""
    return next(r.name for r in load_regions().regions if r.code == code)


def has_no_values(result: QueryResult) -> bool:
    """No rows, or rows whose cells are all NULL: an aggregate over nothing (Step 26 demo:
    USA revenue asked by the Europe sales manager answered "revenue = None")."""
    return result.row_count == 0 or all(cell is None for row in result.rows for cell in row)


def empty_message(state: AgentState, suggestion: str, region_note: str | None = None) -> str:
    tables = state.generated.tables_used if state.generated else []
    entity = _ENTITY_NAMES.get(tables[0], tables[0].replace("_", " ")) if tables else "results"
    period = f" ({state.date_range.label})" if state.date_range else ""
    region = state.user.region if state.user else None
    note = f" {region_note.format(region=region_name(region))}" if region and region_note else ""
    return f"No {entity} matched these filters{period}.{note} {suggestion}"


def make_answer_node(deps: AgentDeps) -> NodeFn:
    config = deps.agent_config.answer

    @agent_node(NodeName.ANSWER)
    async def answer_and_visualization(state: AgentState) -> NodeUpdate:
        result = state.execution
        if result is None:
            raise AppError("answer reached without a result")
        label = config.low_confidence_label if state.low_confidence else None
        confidence = Confidence.LOW if state.low_confidence else Confidence.MEDIUM
        title = state.intent.summary if state.intent else None
        chart = choose_chart(
            result.columns,
            result.rows,
            truncated=result.truncated,
            config=config.chart,
            title=title,
        )
        if has_no_values(result):
            text = empty_message(state, config.empty_suggestion, config.empty_region_note)
            answer = Answer(
                text=text,
                sql_description=template_description(state),
                chart=chart,
                grounded=True,
                source="empty",
                low_confidence_label=label,
                confidence=confidence,
            )
            return {"status": QuestionStatus.ANSWERED, "answer": answer, "user_message": text}

        shown = min(config.rows_for_llm, result.row_count)
        allowed_numbers = context_numbers(
            state.question,
            date_range_text(state),
            " ".join(state.assumptions),
            extra=[result.row_count, shown, state.top_n],
        )
        prompt = load_prompt("answer", deps.llm_config.prompts["answer"])
        messages = [
            *deps.system_messages(),
            *prompt.to_chat_prompt().format_messages(
                question=state.intent.summary if state.intent else state.question,
                date_range=date_range_text(state),
                assumptions="; ".join(state.assumptions) or "none",
                columns=", ".join(result.columns),
                rows=rows_text(result, config.rows_for_llm, personal_columns()),
                row_count=str(result.row_count),
                shown_rows=str(shown),
                sql=state.executed_sql or "",
            ),
        ]

        def grounded(draft: AnswerDraft) -> None:
            check = check_grounding(
                draft.explanation, result.columns, result.rows, context_numbers=allowed_numbers
            )
            if not check.grounded:
                raise ValueError(
                    "these numbers are not in the result rows: " + ", ".join(check.ungrounded)
                )
            problems = item_problems(draft.items, result)
            if problems:
                raise ValueError("items must be rows of the result: " + "; ".join(problems[:5]))

        budget = deps.budget_for(state)
        try:
            reply = await ainvoke_structured(
                deps.llm,
                messages,
                AnswerDraft,
                budget=budget,
                node=NodeName.ANSWER.value,
                max_regenerations=config.max_regenerations,
                check=grounded,
            )
            items = [
                AnswerItem(
                    label=i.label,
                    value=i.value,
                    detail=None if i.detail and _ID_DETAIL.search(i.detail) else i.detail,
                )
                for i in reply.value.items
            ] or items_from_rows(result)
            answer = Answer(
                text=reply.value.explanation,
                sql_description=reply.value.sql_description,
                chart=chart,
                items=items,
                grounded=True,
                source="llm",
                low_confidence_label=label,
                confidence=confidence,
            )
            regenerations = reply.regenerations
        except AppError:
            # Ungrounded twice, malformed, over budget or LLM unavailable: the rows are still
            # correct, so answer from them with a plain template.
            period = state.date_range.label if state.date_range else None
            answer = Answer(
                text=template_answer(result, period),
                sql_description=template_description(state),
                chart=chart,
                items=items_from_rows(result),
                grounded=True,
                source="template",
                low_confidence_label=label,
                confidence=confidence,
            )
            regenerations = config.max_regenerations
        return {
            "status": QuestionStatus.ANSWERED,
            "answer": answer,
            "user_message": answer.text,
            "usage": usage_of(budget),
            "regeneration_attempts": state.regeneration_attempts + regenerations,
        }

    return answer_and_visualization
