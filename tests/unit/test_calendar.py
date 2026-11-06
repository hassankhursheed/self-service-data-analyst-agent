"""Step 8: business calendar date resolution (pure unit tests, no LLM, no database)."""

import datetime as dt
import inspect
from pathlib import Path

import pytest
import yaml

import app.semantic.calendar as calendar_module
from app.core.enums import WeekStart
from app.semantic.calendar import (
    CALENDAR_FILE,
    CalendarConfig,
    DateRange,
    PeriodRule,
    UnresolvedPeriod,
    load_calendar,
    resolve_period,
)

D = dt.date


def cal(ref: dt.date, *, week_start: str = "monday", fiscal_start: int = 1) -> CalendarConfig:
    return CalendarConfig(
        version=1,
        reference_date=ref,
        time_zone="UTC",
        fiscal_year_start_month=fiscal_start,
        week_start=WeekStart(week_start),
    )


def resolved(phrase: str, calendar: CalendarConfig) -> DateRange:
    result = resolve_period(phrase, calendar)
    assert isinstance(result, DateRange), f"{phrase!r} -> {result}"
    return result


REF = cal(D(2025, 5, 6))  # business today from config/calendar.yaml (a Tuesday)


@pytest.mark.parametrize(
    ("phrase", "start", "end", "rule"),
    [
        ("today", D(2025, 5, 6), D(2025, 5, 6), PeriodRule.TODAY),
        ("yesterday", D(2025, 5, 5), D(2025, 5, 5), PeriodRule.YESTERDAY),
        ("this week", D(2025, 5, 5), D(2025, 5, 6), PeriodRule.CURRENT_TO_DATE),
        ("last week", D(2025, 4, 28), D(2025, 5, 4), PeriodRule.PREVIOUS),
        ("previous week", D(2025, 4, 28), D(2025, 5, 4), PeriodRule.PREVIOUS),
        ("this month", D(2025, 5, 1), D(2025, 5, 6), PeriodRule.CURRENT_TO_DATE),
        ("last month", D(2025, 4, 1), D(2025, 4, 30), PeriodRule.PREVIOUS),
        ("previous month", D(2025, 4, 1), D(2025, 4, 30), PeriodRule.PREVIOUS),
        ("this quarter", D(2025, 4, 1), D(2025, 5, 6), PeriodRule.CURRENT_TO_DATE),
        ("last quarter", D(2025, 1, 1), D(2025, 3, 31), PeriodRule.PREVIOUS),
        ("previous quarter", D(2025, 1, 1), D(2025, 3, 31), PeriodRule.PREVIOUS),
        ("the quarter before last", D(2024, 10, 1), D(2024, 12, 31), PeriodRule.BEFORE_PREVIOUS),
        ("this year", D(2025, 1, 1), D(2025, 5, 6), PeriodRule.CURRENT_TO_DATE),
        ("last year", D(2024, 1, 1), D(2024, 12, 31), PeriodRule.PREVIOUS),
        ("previous year", D(2024, 1, 1), D(2024, 12, 31), PeriodRule.PREVIOUS),
        ("year to date", D(2025, 1, 1), D(2025, 5, 6), PeriodRule.CURRENT_TO_DATE),
        ("YTD", D(2025, 1, 1), D(2025, 5, 6), PeriodRule.CURRENT_TO_DATE),
        ("month to date", D(2025, 5, 1), D(2025, 5, 6), PeriodRule.CURRENT_TO_DATE),
        ("last 7 days", D(2025, 4, 30), D(2025, 5, 6), PeriodRule.LAST_N_DAYS),
        ("past 30 days", D(2025, 4, 7), D(2025, 5, 6), PeriodRule.LAST_N_DAYS),
        ("last 3 months", D(2025, 2, 1), D(2025, 4, 30), PeriodRule.LAST_N_PERIODS),
        ("last two weeks", D(2025, 4, 21), D(2025, 5, 4), PeriodRule.LAST_N_PERIODS),
        ("last 2 quarters", D(2024, 10, 1), D(2025, 3, 31), PeriodRule.LAST_N_PERIODS),
        ("March", D(2025, 3, 1), D(2025, 3, 31), PeriodRule.NAMED_MONTH),
        ("in December", D(2024, 12, 1), D(2024, 12, 31), PeriodRule.NAMED_MONTH),
        ("March 2024", D(2024, 3, 1), D(2024, 3, 31), PeriodRule.NAMED_MONTH),
        ("sep 2023", D(2023, 9, 1), D(2023, 9, 30), PeriodRule.NAMED_MONTH),
        ("Q1 2025", D(2025, 1, 1), D(2025, 3, 31), PeriodRule.NAMED_QUARTER),
        ("2024 Q4", D(2024, 10, 1), D(2024, 12, 31), PeriodRule.NAMED_QUARTER),
        ("Q3", D(2024, 7, 1), D(2024, 9, 30), PeriodRule.NAMED_QUARTER),
        ("the first quarter of 2024", D(2024, 1, 1), D(2024, 3, 31), PeriodRule.NAMED_QUARTER),
        ("2024", D(2024, 1, 1), D(2024, 12, 31), PeriodRule.NAMED_YEAR),
        ("in 2023", D(2023, 1, 1), D(2023, 12, 31), PeriodRule.NAMED_YEAR),
        ("FY2024", D(2024, 1, 1), D(2024, 12, 31), PeriodRule.NAMED_FISCAL_YEAR),
        ("from 2024-01-01 to 2024-03-31", D(2024, 1, 1), D(2024, 3, 31), PeriodRule.EXPLICIT_RANGE),
        ("between 1 Jan 2024 and 31 Mar 2024", D(2024, 1, 1), D(2024, 3, 31), PeriodRule.EXPLICIT_RANGE),  # noqa: E501
        ("March 5, 2025 until April 2, 2025", D(2025, 3, 5), D(2025, 4, 2), PeriodRule.EXPLICIT_RANGE),  # noqa: E501
        ("on 2025-02-14", D(2025, 2, 14), D(2025, 2, 14), PeriodRule.EXPLICIT_DATE),
    ],
)  # fmt: skip
def test_supported_phrases_on_the_configured_reference_date(
    phrase: str, start: dt.date, end: dt.date, rule: PeriodRule
) -> None:
    result = resolved(phrase, REF)
    assert (result.from_date, result.to_date, result.rule) == (start, end, rule)
    assert result.reference_date == D(2025, 5, 6)


def test_labels_show_the_resolved_range() -> None:
    assert resolved("last quarter", REF).label == "Last quarter = 1 Jan to 31 Mar 2025"
    assert resolved("today", REF).label == "Today = 6 May 2025"
    assert resolved("last 3 months", REF).label == "Last 3 months = 1 Feb to 30 Apr 2025"
    assert (
        resolved("the quarter before last", REF).label
        == "The quarter before last = 1 Oct to 31 Dec 2024"
    )
    assert resolved("ytd", REF).label == "Year to date = 1 Jan to 6 May 2025"


def test_range_across_years_shows_both_years() -> None:
    result = resolved("from 2024-12-15 to 2025-01-10", REF)
    assert result.label == "Selected range = 15 Dec 2024 to 10 Jan 2025"


def test_named_period_without_year_states_the_assumption() -> None:
    assert resolved("March", REF).assumption == "No year given: used the most recent March."
    assert resolved("March 2024", REF).assumption is None


def test_period_running_past_business_today_is_cut_and_labelled() -> None:
    result = resolved("2025", REF)
    assert (result.from_date, result.to_date) == (D(2025, 1, 1), D(2025, 5, 6))
    assert result.cut_at_reference_date is True
    assert result.label.endswith("(to date)")


# --- boundaries -----------------------------------------------------------------------------


def test_first_day_of_a_quarter() -> None:
    c = cal(D(2025, 4, 1))
    assert (resolved("this quarter", c).from_date, resolved("this quarter", c).to_date) == (
        D(2025, 4, 1),
        D(2025, 4, 1),
    )
    last = resolved("last quarter", c)
    assert (last.from_date, last.to_date) == (D(2025, 1, 1), D(2025, 3, 31))


def test_last_day_of_a_quarter_is_still_this_quarter() -> None:
    c = cal(D(2025, 3, 31))
    this_q = resolved("this quarter", c)
    assert (this_q.from_date, this_q.to_date) == (D(2025, 1, 1), D(2025, 3, 31))
    last = resolved("last quarter", c)
    assert (last.from_date, last.to_date) == (D(2024, 10, 1), D(2024, 12, 31))


def test_year_boundary() -> None:
    c = cal(D(2025, 1, 1))  # a Wednesday
    assert (resolved("last year", c).from_date, resolved("last year", c).to_date) == (
        D(2024, 1, 1),
        D(2024, 12, 31),
    )
    assert resolved("last month", c).from_date == D(2024, 12, 1)
    assert resolved("last quarter", c).from_date == D(2024, 10, 1)
    assert resolved("yesterday", c).from_date == D(2024, 12, 31)
    week = resolved("last week", c)
    assert (week.from_date, week.to_date) == (D(2024, 12, 23), D(2024, 12, 29))
    assert resolved("this week", c).from_date == D(2024, 12, 30)


def test_brief_example_reference_date() -> None:
    """With the brief's example 2025-12-31, last quarter is the last complete one (Q3)."""
    c = cal(D(2025, 12, 31))
    last = resolved("last quarter", c)
    assert last.label == "Last quarter = 1 Jul to 30 Sep 2025"
    assert resolved("this quarter", c).label == "This quarter = 1 Oct to 31 Dec 2025"


@pytest.mark.parametrize(
    ("ref", "phrase", "start", "end"),
    [
        (D(2024, 3, 1), "last month", D(2024, 2, 1), D(2024, 2, 29)),
        (D(2024, 3, 1), "February", D(2024, 2, 1), D(2024, 2, 29)),
        (D(2025, 3, 1), "February", D(2025, 2, 1), D(2025, 2, 28)),
        (D(2024, 3, 1), "last 30 days", D(2024, 2, 1), D(2024, 3, 1)),
        (D(2025, 3, 1), "last 30 days", D(2025, 1, 31), D(2025, 3, 1)),
        (D(2024, 3, 1), "yesterday", D(2024, 2, 29), D(2024, 2, 29)),
        (D(2025, 5, 6), "February 2024", D(2024, 2, 1), D(2024, 2, 29)),
    ],
)
def test_leap_years(ref: dt.date, phrase: str, start: dt.date, end: dt.date) -> None:
    result = resolved(phrase, cal(ref))
    assert (result.from_date, result.to_date) == (start, end)


@pytest.mark.parametrize(
    ("week_start", "this_week", "last_week"),
    [
        ("monday", (D(2025, 4, 28), D(2025, 5, 4)), (D(2025, 4, 21), D(2025, 4, 27))),
        ("sunday", (D(2025, 5, 4), D(2025, 5, 4)), (D(2025, 4, 27), D(2025, 5, 3))),
    ],
)
def test_week_start_on_a_sunday_reference_date(
    week_start: str, this_week: tuple[dt.date, dt.date], last_week: tuple[dt.date, dt.date]
) -> None:
    c = cal(D(2025, 5, 4), week_start=week_start)  # 4 May 2025 is a Sunday
    this = resolved("this week", c)
    last = resolved("last week", c)
    assert (this.from_date, this.to_date) == this_week
    assert (last.from_date, last.to_date) == last_week


def test_fiscal_year_starting_in_april() -> None:
    c = cal(D(2025, 5, 6), fiscal_start=4)
    this_year = resolved("this year", c)
    assert (this_year.from_date, this_year.to_date) == (D(2025, 4, 1), D(2025, 5, 6))
    last_year = resolved("last year", c)
    assert (last_year.from_date, last_year.to_date) == (D(2024, 4, 1), D(2025, 3, 31))
    assert resolved("this quarter", c).from_date == D(2025, 4, 1)
    assert resolved("last quarter", c).from_date == D(2025, 1, 1)
    fy = resolved("FY2025", c)
    assert (fy.from_date, fy.to_date) == (D(2024, 4, 1), D(2025, 3, 31))
    q1 = resolved("Q1 2025", c)
    assert (q1.from_date, q1.to_date, q1.label) == (
        D(2024, 4, 1),
        D(2024, 6, 30),
        "Q1 FY2025 = 1 Apr to 30 Jun 2024",
    )
    calendar_year = resolved("2024", c)  # a plain year is always a calendar year
    assert (calendar_year.from_date, calendar_year.to_date) == (D(2024, 1, 1), D(2024, 12, 31))


# --- config and unresolved ------------------------------------------------------------------


def test_the_shipped_config_loads() -> None:
    loaded = load_calendar()
    assert loaded.reference_date == D(2025, 5, 6)
    assert loaded.week_start is WeekStart.MONDAY


def test_changing_the_reference_date_in_config_changes_the_result(tmp_path: Path) -> None:
    data = yaml.safe_load(CALENDAR_FILE.read_text("utf-8"))
    data["reference_date"] = "2025-12-31"
    path = tmp_path / "calendar.yaml"
    path.write_text(yaml.safe_dump(data), "utf-8")
    before = resolved("last quarter", load_calendar())
    after = resolved("last quarter", load_calendar(path))
    assert (before.from_date, after.from_date) == (D(2025, 1, 1), D(2025, 7, 1))


@pytest.mark.parametrize(
    "phrase",
    [
        "",
        "   ",
        "someday",
        "recently",
        "the good old days",
        "last blah months",
        "2024-02-30",
        "from 2024-03-31 to 2024-01-01",
        "June 2025",
        "next month",
        "Q5 2024",
    ],
)
def test_unknown_or_impossible_phrases_are_unresolved(phrase: str) -> None:
    result = resolve_period(phrase, REF)
    assert isinstance(result, UnresolvedPeriod)
    assert result.status == "unresolved"
    assert result.reason


def test_never_uses_the_real_current_date() -> None:
    source = inspect.getsource(calendar_module)
    assert "today()" not in source
    assert ".now(" not in source
