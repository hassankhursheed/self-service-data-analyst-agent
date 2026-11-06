"""Business calendar: resolve time phrases to fixed, explainable date ranges.

Everything is relative to the configured business reference date ("business today",
config/calendar.yaml), never the real current date. Rules and examples are listed in
docs/business-calendar.md.
"""

import calendar as _cal
import datetime as dt
import re
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import PROJECT_ROOT
from app.core.enums import WeekStart
from app.core.yaml_config import load_yaml_model

CALENDAR_FILE = PROJECT_ROOT / "config" / "calendar.yaml"

_MONTHS = {
    name: i
    for i in range(1, 13)
    for name in (_cal.month_name[i].lower(), _cal.month_abbr[i].lower())
}
_MONTHS["sept"] = 9
_MONTH_ABBR = [""] + [_cal.month_abbr[i] for i in range(1, 13)]
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14,
    "thirty": 30, "ninety": 90,
}  # fmt: skip
_ORDINAL_QUARTERS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2,
                     "3rd": 3, "4th": 4}  # fmt: skip
_UNITS = ("day", "week", "month", "quarter", "year")


class CalendarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    reference_date: dt.date
    time_zone: str = Field(min_length=1)
    fiscal_year_start_month: int = Field(ge=1, le=12)
    week_start: WeekStart


def load_calendar(path: Path = CALENDAR_FILE) -> CalendarConfig:
    return load_yaml_model(path, CalendarConfig)


class PeriodRule(StrEnum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    CURRENT_TO_DATE = "current_period_to_date"
    PREVIOUS = "previous_complete_period"
    BEFORE_PREVIOUS = "period_before_previous"
    LAST_N_DAYS = "last_n_days"
    LAST_N_PERIODS = "last_n_complete_periods"
    NAMED_MONTH = "named_month"
    NAMED_QUARTER = "named_quarter"
    NAMED_YEAR = "named_year"
    NAMED_FISCAL_YEAR = "named_fiscal_year"
    EXPLICIT_DATE = "explicit_date"
    EXPLICIT_RANGE = "explicit_range"


class DateRange(BaseModel):
    """A resolved period. ``to_date`` never goes past the reference date."""

    model_config = ConfigDict(frozen=True)

    status: Literal["resolved"] = "resolved"
    phrase: str
    from_date: dt.date
    to_date: dt.date
    label: str
    rule: PeriodRule
    assumption: str | None = None
    cut_at_reference_date: bool = False
    reference_date: dt.date


class UnresolvedPeriod(BaseModel):
    """The phrase could not be turned into dates; the agent should ask the user."""

    model_config = ConfigDict(frozen=True)

    status: Literal["unresolved"] = "unresolved"
    phrase: str
    reason: str
    reference_date: dt.date


PeriodResolution = DateRange | UnresolvedPeriod


# --- calendar arithmetic -------------------------------------------------------------


def _add_months(day: dt.date, months: int) -> dt.date:
    """Shift to the first of the month ``months`` away (``day`` must be a 1st)."""
    index = day.year * 12 + (day.month - 1) + months
    return dt.date(index // 12, index % 12 + 1, 1)


def _month_end(start: dt.date) -> dt.date:
    return _add_months(start, 1) - dt.timedelta(days=1)


def _period_start(unit: str, day: dt.date, cal: CalendarConfig) -> dt.date:
    if unit == "day":
        return day
    if unit == "week":
        first = 0 if cal.week_start is WeekStart.MONDAY else 6
        return day - dt.timedelta(days=(day.weekday() - first) % 7)
    month_start = day.replace(day=1)
    if unit == "month":
        return month_start
    offset = (day.month - cal.fiscal_year_start_month) % 12
    fiscal_year_start = _add_months(month_start, -offset)
    if unit == "year":
        return fiscal_year_start
    return _add_months(fiscal_year_start, (offset // 3) * 3)  # quarter


def _shift(unit: str, start: dt.date, n: int) -> dt.date:
    if unit == "day":
        return start + dt.timedelta(days=n)
    if unit == "week":
        return start + dt.timedelta(weeks=n)
    return _add_months(start, n * {"month": 1, "quarter": 3, "year": 12}[unit])


def _fmt(day: dt.date, with_year: bool = True) -> str:
    text = f"{day.day} {_MONTH_ABBR[day.month]}"
    return f"{text} {day.year}" if with_year else text


def _label(title: str, start: dt.date, end: dt.date) -> str:
    if start == end:
        return f"{title} = {_fmt(start)}"
    return f"{title} = {_fmt(start, with_year=start.year != end.year)} to {_fmt(end)}"


def fiscal_year_name(start: dt.date) -> int:
    """Fiscal years are named after the calendar year in which they end."""
    return (_add_months(start, 12) - dt.timedelta(days=1)).year


# --- parsing helpers --------------------------------------------------------------------


def _normalise(phrase: str) -> str:
    text = phrase.lower().strip()
    text = re.sub(r"[,!?]", " ", text)
    text = re.sub(r"\b(in|during|for|over|of|the|within)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


_DATE_PATTERNS = (
    re.compile(r"^(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})$"),
    re.compile(r"^(?P<d>\d{1,2})(?:st|nd|rd|th)? (?P<mon>[a-z]+)\.? (?P<y>\d{4})$"),
    re.compile(r"^(?P<mon>[a-z]+)\.? (?P<d>\d{1,2})(?:st|nd|rd|th)? (?P<y>\d{4})$"),
)


def _parse_date(text: str) -> dt.date | None:
    text = text.strip()
    for pattern in _DATE_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        parts = match.groupdict()
        month = (
            int(parts["m"])
            if "m" in parts and parts.get("m")
            else _MONTHS.get(parts.get("mon") or "")
        )
        if month is None:
            return None
        try:
            return dt.date(int(parts["y"]), month, int(parts["d"]))
        except ValueError:
            return None
    return None


# --- resolution ---------------------------------------------------------------------------


class _Builder:
    def __init__(self, phrase: str, cal: CalendarConfig) -> None:
        self.phrase = phrase
        self.cal = cal
        self.ref = cal.reference_date

    def unresolved(self, reason: str) -> UnresolvedPeriod:
        return UnresolvedPeriod(phrase=self.phrase, reason=reason, reference_date=self.ref)

    def make(
        self,
        title: str,
        start: dt.date,
        end: dt.date,
        rule: PeriodRule,
        assumption: str | None = None,
    ) -> PeriodResolution:
        if start > end:
            return self.unresolved("the start date is after the end date")
        if start > self.ref:
            return self.unresolved(
                f"the period starts after business today ({_fmt(self.ref)}); there is no data yet"
            )
        cut = end > self.ref
        end = min(end, self.ref)
        label = _label(title, start, end) + (" (to date)" if cut else "")
        return DateRange(
            phrase=self.phrase,
            from_date=start,
            to_date=end,
            label=label,
            rule=rule,
            assumption=assumption,
            cut_at_reference_date=cut,
            reference_date=self.ref,
        )


def resolve_period(phrase: str, cal: CalendarConfig) -> PeriodResolution:
    """Resolve a time phrase such as "last quarter" against the business reference date."""
    b = _Builder(phrase, cal)
    text = _normalise(phrase)
    ref = cal.reference_date
    if not text:
        return b.unresolved("no time period given")

    if text == "today":
        return b.make("Today", ref, ref, PeriodRule.TODAY)
    if text == "yesterday":
        day = ref - dt.timedelta(days=1)
        return b.make("Yesterday", day, day, PeriodRule.YESTERDAY)

    to_date = {"ytd": "year", "qtd": "quarter", "mtd": "month", "wtd": "week"}
    match = re.fullmatch(r"(?:this|current) (week|month|quarter|year)", text) or re.fullmatch(
        r"(week|month|quarter|year) to date", text
    )
    unit = match.group(1) if match else to_date.get(text)
    if unit:
        start = _period_start(unit, ref, cal)
        title = (
            f"This {unit}" if text.startswith(("this", "current")) else f"{unit.title()} to date"
        )
        return b.make(title, start, ref, PeriodRule.CURRENT_TO_DATE)

    match = re.fullmatch(r"(?:last|previous|prior|past) (week|month|quarter|year)", text)
    if match:
        unit = match.group(1)
        start = _shift(unit, _period_start(unit, ref, cal), -1)
        end = _period_start(unit, ref, cal) - dt.timedelta(days=1)
        return b.make(f"Last {unit}", start, end, PeriodRule.PREVIOUS)

    match = re.fullmatch(r"(week|month|quarter|year) before last", text)
    if match:
        unit = match.group(1)
        current = _period_start(unit, ref, cal)
        start = _shift(unit, current, -2)
        end = _shift(unit, current, -1) - dt.timedelta(days=1)
        return b.make(f"The {unit} before last", start, end, PeriodRule.BEFORE_PREVIOUS)

    match = re.fullmatch(
        r"(?:last|past|previous|prior) (\w+) (day|week|month|quarter|year)s?", text
    )
    if match:
        n = _number(match.group(1))
        unit = match.group(2)
        if n is None or n < 1:
            return b.unresolved(f"could not read the number {match.group(1)!r}")
        if unit == "day":
            start = ref - dt.timedelta(days=n - 1)
            return b.make(f"Last {n} days", start, ref, PeriodRule.LAST_N_DAYS)
        current = _period_start(unit, ref, cal)
        start = _shift(unit, current, -n)
        end = current - dt.timedelta(days=1)
        return b.make(f"Last {n} {unit}s", start, end, PeriodRule.LAST_N_PERIODS)

    resolved = (
        _named_month(text, b)
        or _named_quarter(text, b)
        or _named_year(text, b)
        or _explicit(text, b)
    )
    if resolved is not None:
        return resolved
    return b.unresolved(
        "this time period is not recognised; please give a month, quarter, year or a date range"
    )


def _named_month(text: str, b: _Builder) -> PeriodResolution | None:
    match = re.fullmatch(r"([a-z]+)\.?(?: (\d{4}))?", text)
    if not match or match.group(1) not in _MONTHS:
        return None
    month = _MONTHS[match.group(1)]
    if match.group(2):
        start = dt.date(int(match.group(2)), month, 1)
        assumption = None
    else:
        start = dt.date(b.ref.year, month, 1)
        if start > b.ref:
            start = dt.date(b.ref.year - 1, month, 1)
        assumption = f"No year given: used the most recent {_cal.month_name[month]}."
    title = f"{_cal.month_name[month]} {start.year}"
    return b.make(title, start, _month_end(start), PeriodRule.NAMED_MONTH, assumption)


def _named_quarter(text: str, b: _Builder) -> PeriodResolution | None:
    quarter = year = None
    for pattern in (
        r"q([1-4])(?: (\d{4}))?",
        r"(\d{4}) q([1-4])",
        r"(first|second|third|fourth|1st|2nd|3rd|4th) quarter(?: (\d{4}))?",
    ):
        match = re.fullmatch(pattern, text)
        if not match:
            continue
        groups = match.groups()
        if pattern.startswith(r"(\d{4})"):
            year, quarter = int(groups[0]), int(groups[1])
        else:
            quarter = _ORDINAL_QUARTERS.get(groups[0]) or int(groups[0])
            year = int(groups[1]) if groups[1] else None
        break
    if quarter is None:
        return None
    cal = b.cal
    if year is None:
        current_fy_start = _period_start("year", b.ref, cal)
        start = _add_months(current_fy_start, (quarter - 1) * 3)
        if start > b.ref:
            start = _add_months(start, -12)
        assumption = f"No year given: used the most recent Q{quarter}."
    else:
        fy_start = dt.date(year, cal.fiscal_year_start_month, 1)
        if cal.fiscal_year_start_month != 1:
            fy_start = _add_months(fy_start, -12)  # FY named by the year it ends in
        start = _add_months(fy_start, (quarter - 1) * 3)
        assumption = None
    fy = fiscal_year_name(_period_start("year", start, cal))
    title = f"Q{quarter} {fy}" if cal.fiscal_year_start_month == 1 else f"Q{quarter} FY{fy}"
    end = _add_months(start, 3) - dt.timedelta(days=1)
    return b.make(title, start, end, PeriodRule.NAMED_QUARTER, assumption)


def _named_year(text: str, b: _Builder) -> PeriodResolution | None:
    match = re.fullmatch(r"(\d{4})", text)
    if match:
        year = int(match.group(1))
        return b.make(str(year), dt.date(year, 1, 1), dt.date(year, 12, 31), PeriodRule.NAMED_YEAR)
    match = re.fullmatch(r"(?:fy|fiscal year) ?(\d{4})", text)
    if match:
        year = int(match.group(1))
        end_start = dt.date(year, b.cal.fiscal_year_start_month, 1)
        start = end_start if b.cal.fiscal_year_start_month == 1 else _add_months(end_start, -12)
        end = _add_months(start, 12) - dt.timedelta(days=1)
        return b.make(f"FY{year}", start, end, PeriodRule.NAMED_FISCAL_YEAR)
    return None


def _explicit(text: str, b: _Builder) -> PeriodResolution | None:
    match = re.fullmatch(r"(?:from |between )?(.+?) (?:to|until|through|and|-) (.+)", text)
    if match:
        start, end = _parse_date(match.group(1)), _parse_date(match.group(2))
        if start and end:
            return b.make("Selected range", start, end, PeriodRule.EXPLICIT_RANGE)
    single = _parse_date(re.sub(r"^on ", "", text))
    if single:
        return b.make(_fmt(single), single, single, PeriodRule.EXPLICIT_DATE)
    return None
