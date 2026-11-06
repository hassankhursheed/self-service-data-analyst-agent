"""Grounding check: every number in an explanation must come from the query result.

A number in the text is grounded when it matches (docs/answers-and-charts.md):
- a numeric result value, allowing for rounding to the precision written, thousands
  separators and scale words or suffixes ("12.3k", "1.2 million");
- for a percentage: a result value already in percent, a fraction x 100, a share of its
  column total, or the change between two values of the same column;
- context numbers: the row count, top N, and the numbers in the question and the resolved
  date range (years, days).
"""

import re
from collections.abc import Sequence
from decimal import Decimal
from itertools import permutations
from typing import Any

from pydantic import BaseModel, ConfigDict

_NUMBER = re.compile(
    r"(?<![\w.])(?P<sign>[-+])?\$?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<suffix>\s?(?:%|percent\b|k\b|K\b|thousand\b|m\b|M\b|million\b|bn\b|billion\b))?",
)
_SCALES = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}


class MentionedNumber(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    value: float
    tolerance: float
    percent: bool


class GroundingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    grounded: bool
    ungrounded: list[str]
    checked: int


def extract_numbers(text: str) -> list[MentionedNumber]:
    found: list[MentionedNumber] = []
    for match in _NUMBER.finditer(text):
        raw = match.group("num")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        value = float(raw.replace(",", ""))
        if match.group("sign") == "-":
            value = -value
        suffix = (match.group("suffix") or "").strip().lower()
        percent = suffix in {"%", "percent"}
        scale = _SCALES.get(suffix, 1.0)
        found.append(
            MentionedNumber(
                text=match.group(0).strip(),
                value=value * scale,
                tolerance=0.5 * 10**-decimals * scale + 1e-9,
                percent=percent,
            )
        )
    return found


def _numeric(value: Any) -> float | None:  # noqa: ANN401
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        return float(value)
    return None


def _close(mentioned: MentionedNumber, candidate: float) -> bool:
    return abs(abs(mentioned.value) - abs(candidate)) <= mentioned.tolerance


def check_grounding(
    text: str,
    columns: list[str],
    rows: list[tuple[Any, ...]],
    *,
    context_numbers: set[float] | None = None,
) -> GroundingResult:
    values = [v for r in rows for c in r if (v := _numeric(c)) is not None]
    by_column = [
        [v for r in rows if (v := _numeric(r[i])) is not None] for i in range(len(columns))
    ]
    allowed_context = context_numbers or set()
    ungrounded: list[str] = []
    mentioned = extract_numbers(text)
    for number in mentioned:
        if any(_close(number, c) for c in allowed_context):
            continue
        if not number.percent:
            if any(_close(number, v) for v in values):
                continue
            ungrounded.append(number.text)
            continue
        candidates = list(values) + [v * 100 for v in values]
        for column in by_column:
            total = sum(column)
            if total:
                candidates.extend(100 * v / total for v in column)
            candidates.extend(100 * (a - b) / b for a, b in permutations(column, 2) if b)
            candidates.extend(100 * a / b for a, b in permutations(column, 2) if b)
        if not any(_close(number, c) for c in candidates):
            ungrounded.append(number.text)
    return GroundingResult(grounded=not ungrounded, ungrounded=ungrounded, checked=len(mentioned))


def context_numbers(*texts: str, extra: Sequence[int | None] = ()) -> set[float]:
    """Numbers that may appear without being in the result (question, dates, counts)."""
    numbers = {n.value for t in texts for n in extract_numbers(t)}
    numbers.update(float(x) for x in extra if x is not None)
    return numbers
