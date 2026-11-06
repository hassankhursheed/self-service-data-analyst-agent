"""N-10 Answer and Visualization: grounded explanation, SQL description and chart.

- Empty result: an honest "No ... matched these filters" message and a suggestion; no LLM.
- Otherwise the LLM sees only the first ``rows_for_llm`` rows (role-allowed columns only)
  and returns JSON with an explanation and a one-line SQL description.
- Every number in the explanation must be grounded in the result (app/agent/grounding.py);
  one regeneration, then a plain template answer built from the rows. An unavailable LLM
  also falls back to the template, because the result itself is still correct.
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.charts import choose_chart
from app.agent.deps import AgentDeps, usage_of
from app.agent.grounding import check_grounding, context_numbers
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.nodes.sql_context import date_range_text
from app.agent.state import AgentState, Answer
from app.core.enums import Confidence, NodeName, QuestionStatus
from app.core.errors import AppError
from app.core.llm import ainvoke_structured
from app.core.prompts import load_prompt
from app.db.analytics import QueryResult

_ENTITY_NAMES = {"order_details": "order lines"}


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    explanation: str = Field(min_length=1, max_length=1200)
    sql_description: str = Field(min_length=1, max_length=300)


def format_value(value: Any) -> str:  # noqa: ANN401 (result cells have any SQL type)
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float | Decimal):
        return f"{float(value):,.2f}".rstrip("0").rstrip(".")
    return str(value)


def rows_text(result: QueryResult, limit: int) -> str:
    lines = [" | ".join(format_value(v) for v in row) for row in result.rows[:limit]]
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
    shown = [
        ", ".join(
            f"{c.replace('_', ' ')} {format_value(v)}"
            for c, v in zip(result.columns, row, strict=False)
        )
        for row in result.rows[:3]
    ]
    more = " (cut at the row limit)" if result.truncated else ""
    return (
        f"The query returned {result.row_count} rows{period}{more}. "
        f"Top results: {'; '.join(shown)}."
    )


def template_description(state: AgentState) -> str:
    tables = state.generated.tables_used if state.generated else []
    names = ", ".join(_ENTITY_NAMES.get(t, t.replace("_", " ")) for t in tables) or "the data"
    period = f" for {state.date_range.label.split(' = ')[-1]}" if state.date_range else ""
    return f"Reads {names}{period}."


def empty_message(state: AgentState, suggestion: str) -> str:
    tables = state.generated.tables_used if state.generated else []
    entity = _ENTITY_NAMES.get(tables[0], tables[0].replace("_", " ")) if tables else "results"
    period = f" ({state.date_range.label})" if state.date_range else ""
    return f"No {entity} matched these filters{period}. {suggestion}"


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
        if result.row_count == 0:
            text = empty_message(state, config.empty_suggestion)
            answer = Answer(
                text=text, sql_description=template_description(state), chart=chart,
                grounded=True, source="empty", low_confidence_label=label, confidence=confidence,
            )  # fmt: skip
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
                rows=rows_text(result, config.rows_for_llm),
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
            answer = Answer(
                text=reply.value.explanation,
                sql_description=reply.value.sql_description,
                chart=chart,
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
