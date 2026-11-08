"""Chart selection as a pure function (brief section 17, docs/answers-and-charts.md).

Rules, in order:
1. no rows, or a truncated result -> no chart
2. one row with one numeric value -> metric card
3. a time column plus numeric columns, 2..max_line_points rows -> line
4. a category (text) column plus numeric columns, 2..max_bars rows -> bar
5. anything else -> no chart (the table is shown)

The spec is neutral (type, x, y, data); the UI draws it.
"""

import datetime as dt
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChartType = Literal["line", "bar", "metric_card", "none"]
_TIME_WORDS = ("date", "day", "week", "month", "quarter", "year", "period")


class ChartConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_bars: int = Field(ge=2)
    max_line_points: int = Field(ge=2)
    max_series: int = Field(ge=1)


class ChartSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: ChartType
    x: str | None = None
    y: list[str] = []
    data: list[dict[str, Any]] = []
    title: str | None = None
    reason: str


def json_value(value: Any) -> Any:  # noqa: ANN401 (result cells have any SQL type)
    """Result cell -> JSON-friendly value."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return value


def _is_number(value: Any) -> bool:  # noqa: ANN401
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def is_identifier(column: str) -> bool:
    """IDs are labels, not quantities (Step 26 walk-through: product_id was plotted)."""
    name = column.lower()
    return name == "id" or name.endswith("_id")


def _numeric_columns(columns: list[str], rows: list[tuple[Any, ...]]) -> list[str]:
    return [
        c for i, c in enumerate(columns)
        if not is_identifier(c)
        and rows and all(_is_number(r[i]) or r[i] is None for r in rows)
        and any(_is_number(r[i]) for r in rows)
    ]  # fmt: skip


def _time_column(columns: list[str], rows: list[tuple[Any, ...]]) -> str | None:
    for i, column in enumerate(columns):
        values = [r[i] for r in rows if r[i] is not None]
        if values and all(isinstance(v, dt.date | dt.datetime) for v in values):
            return column
    for column in columns:
        if any(word in column.lower() for word in _TIME_WORDS):
            return column
    return None


def _category_column(columns: list[str], rows: list[tuple[Any, ...]]) -> str | None:
    for i, column in enumerate(columns):
        if rows and all(isinstance(r[i], str) for r in rows):
            return column
    return None


def _records(
    columns: list[str], rows: list[tuple[Any, ...]], keep: list[str]
) -> list[dict[str, Any]]:
    index = [columns.index(c) for c in keep]
    return [{columns[i]: json_value(r[i]) for i in index} for r in rows]


def choose_chart(
    columns: list[str],
    rows: list[tuple[Any, ...]],
    *,
    truncated: bool,
    config: ChartConfig,
    title: str | None = None,
) -> ChartSpec:
    if not rows:
        return ChartSpec(type="none", reason="no rows")
    if truncated:
        return ChartSpec(type="none", reason="result was cut at the row limit; see the table")
    numeric = _numeric_columns(columns, rows)
    if len(rows) == 1 and len(numeric) == 1 and len(columns) <= 2:
        return ChartSpec(
            type="metric_card",
            y=numeric,
            data=_records(columns, rows, columns),
            title=title,
            reason="a single value",
        )
    if not numeric:
        return ChartSpec(type="none", reason="no numeric column to plot")
    time = _time_column(columns, rows)
    if time is not None:
        y = [c for c in numeric if c != time][: config.max_series]
        if y and len(rows) > config.max_line_points:
            return ChartSpec(type="none", reason="too many points for a line chart")
        if y and len(rows) >= 2:
            data = sorted(_records(columns, rows, [time, *y]), key=lambda r: str(r[time]))
            return ChartSpec(
                type="line", x=time, y=y, data=data, title=title, reason="values over time"
            )
    category = _category_column(columns, rows)
    if category is not None:
        y = numeric[: config.max_series]
        if 2 <= len(rows) <= config.max_bars:
            return ChartSpec(
                type="bar",
                x=category,
                y=y,
                data=_records(columns, rows, [category, *y]),
                title=title,
                reason="comparison across categories",
            )
        if len(rows) > config.max_bars:
            return ChartSpec(type="none", reason="too many categories for a bar chart")
    return ChartSpec(type="none", reason="the result shape does not suit a chart")
