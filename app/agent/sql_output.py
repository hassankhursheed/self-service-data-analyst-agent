"""Structured SQL output from the LLM (brief section 15) and its acceptance checks."""

import datetime as dt
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import Confidence
from app.semantic.calendar import DateRange
from app.semantic.retriever import RetrievedContext
from app.semantic.verified import is_single_aggregate, uses_definition


class SqlDateRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    from_date: dt.date = Field(alias="from")
    to_date: dt.date = Field(alias="to")

    @model_validator(mode="after")
    def _ordered(self) -> "SqlDateRange":
        if self.from_date > self.to_date:
            raise ValueError("date_range 'from' is after 'to'")
        return self


class GeneratedSQL(BaseModel):
    """What N-06 and N-09 must return; unknown keys and bad values fail validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sql: str = Field(min_length=1, max_length=20_000)
    tables_used: list[str] = Field(min_length=1)
    metrics_used: list[str] = []
    date_range: SqlDateRange | None = None
    assumptions: list[str] = []
    confidence: Confidence

    @field_validator("metrics_used", "assumptions", mode="before")
    @classmethod
    def _null_is_empty(cls, value: object) -> object:
        """Some models write null for an empty list (Step 22). tables_used stays required."""
        return [] if value is None else value


_DATE_LITERAL = re.compile(r"'(\d{4}-\d{2}-\d{2})'")


def check_period(sql: str, period: DateRange | None) -> None:
    """Raise ValueError when the SQL's dates do not match the resolved period.

    The period's first day must appear, and no date may be after its last day (plus one
    day, for ``< next day`` filters). Earlier dates are allowed, so comparisons with an
    earlier period still work. Found in Step 26: for "last quarter" (Q1 2025) the model
    wrote Q4 2024 dates while the answer was labelled Q1 2025.
    """
    if period is None:
        return
    found = {dt.date.fromisoformat(d) for d in _DATE_LITERAL.findall(sql)}
    if not found:
        return
    latest = period.to_date + dt.timedelta(days=1)
    if period.from_date not in found or any(d > latest for d in found):
        raise ValueError(
            f"use the period from {period.from_date.isoformat()} to {period.to_date.isoformat()} "
            f"in the SQL (it has {', '.join(sorted(d.isoformat() for d in found))})"
        )


def check_against_context(generated: GeneratedSQL, context: RetrievedContext) -> None:
    """Raise ValueError when the reply uses tables or metrics outside the retrieved context."""
    tables = {t.lower() for t in generated.tables_used} - set(context.table_names)
    if tables:
        raise ValueError(f"tables_used outside the allowed context: {sorted(tables)}")
    metrics = {m.lower() for m in generated.metrics_used} - set(context.metric_names)
    if metrics:
        raise ValueError(f"metrics_used outside the allowed context: {sorted(metrics)}")


def check_metric_formulas(generated: GeneratedSQL, context: RetrievedContext) -> None:
    """Raise ValueError when a metric the model says it uses is computed another way.

    The semantic layer decides what a metric means. Found in Step 26 (scenario 9): with
    revenue redefined as gross revenue, the model kept the discount because "the question
    implies net revenue". Checked for single-aggregate definitions (``SUM(...)``,
    ``COUNT(DISTINCT ...)``), which can be compared reliably as text.
    """
    definitions = {m.name: m.definition for m in context.metrics}
    for name in generated.metrics_used:
        definition = definitions.get(name.lower())
        if (
            definition
            and is_single_aggregate(definition)
            and not uses_definition(generated.sql, definition)
        ):
            raise ValueError(f"compute {name} exactly as its definition says: {definition}")


def check_generated(
    generated: GeneratedSQL, context: RetrievedContext, period: DateRange | None
) -> None:
    """All checks on a generated or repaired query before it is validated and run."""
    check_against_context(generated, context)
    check_period(generated.sql, period)
    check_metric_formulas(generated, context)
