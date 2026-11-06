"""Structured SQL output from the LLM (brief section 15) and its acceptance checks."""

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import Confidence
from app.semantic.retriever import RetrievedContext


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


def check_against_context(generated: GeneratedSQL, context: RetrievedContext) -> None:
    """Raise ValueError when the reply uses tables or metrics outside the retrieved context."""
    tables = {t.lower() for t in generated.tables_used} - set(context.table_names)
    if tables:
        raise ValueError(f"tables_used outside the allowed context: {sorted(tables)}")
    metrics = {m.lower() for m in generated.metrics_used} - set(context.metric_names)
    if metrics:
        raise ValueError(f"metrics_used outside the allowed context: {sorted(metrics)}")
