# Business calendar

Brief section 10. Time phrases always resolve to the same, explainable date range, because
they are calculated from a configured **business reference date** ("business today"),
never from the real current date.

- Config: `config/calendar.yaml` (versioned; synced into `app.business_calendar_config` by
  the seed).
- Code: `resolve_period(phrase, calendar)` in `app/semantic/calendar.py`. It returns a
  `DateRange` (`from_date`, `to_date`, `label`, `rule`, optional `assumption`) or an
  `UnresolvedPeriod` with a reason, so the agent can ask a clarifying question.

## Settings

| Setting | Value | Meaning |
| --- | --- | --- |
| `reference_date` | 2025-05-06 | Business today: the last order date after the +27-year shift. |
| `time_zone` | UTC | Dates only; no time of day is involved. |
| `fiscal_year_start_month` | 1 | Fiscal year = calendar year. Quarters are three-month blocks from this month. A fiscal year is named after the calendar year it ends in (with an April start, FY2025 = 1 Apr 2024 to 31 Mar 2025). |
| `week_start` | monday | First day of "this week" / "last week". |

Changing any value in the file changes the results without a code change (tested).

## General rules

1. **"This" = the period containing business today, up to business today.**
2. **"Last" / "previous" / "prior" = the complete period just before the current one.**
   It is always complete, because the current period has started.
3. **Nothing goes past business today.** A period that ends later is cut at business today
   and its label ends in "(to date)". A period that *starts* after business today is
   unresolved ("there is no data yet").
4. **A named month or quarter without a year means the most recent one** that has started
   by business today; the answer states this assumption.
5. **A plain year ("2024") is a calendar year;** "FY2024" is a fiscal year.
6. **Every answer shows the label**, for example "Last quarter = 1 Jan to 31 Mar 2025".
7. **Anything not recognised is unresolved.** There is no fallback to the real date.

## Every rule, with an example

All examples use business today = Tuesday 6 May 2025, week start Monday, fiscal year =
calendar year.

| Rule (`PeriodRule`) | Phrases | Example | Resolves to |
| --- | --- | --- | --- |
| `today` | today | today | Today = 6 May 2025 |
| `yesterday` | yesterday | yesterday | Yesterday = 5 May 2025 |
| `current_period_to_date` | this / current week, month, quarter, year | this week | This week = 5 May to 6 May 2025 |
| | | this month | This month = 1 May to 6 May 2025 |
| | | this quarter | This quarter = 1 Apr to 6 May 2025 |
| | | this year | This year = 1 Jan to 6 May 2025 |
| | year / quarter / month / week to date, YTD, QTD, MTD, WTD | YTD | Year to date = 1 Jan to 6 May 2025 |
| `previous_complete_period` | last / previous / prior / past week, month, quarter, year | last week | Last week = 28 Apr to 4 May 2025 |
| | | last month | Last month = 1 Apr to 30 Apr 2025 |
| | | last quarter | Last quarter = 1 Jan to 31 Mar 2025 |
| | | last year | Last year = 1 Jan to 31 Dec 2024 |
| `period_before_previous` | the week / month / quarter / year before last | the quarter before last | The quarter before last = 1 Oct to 31 Dec 2024 |
| `last_n_days` | last / past N days (N in digits or words) | last 7 days | Last 7 days = 30 Apr to 6 May 2025 (includes today) |
| `last_n_complete_periods` | last N weeks, months, quarters, years | last 3 months | Last 3 months = 1 Feb to 30 Apr 2025 (the current month is excluded) |
| | | last two weeks | Last 2 weeks = 21 Apr to 4 May 2025 |
| `named_month` | March, Mar, in December, March 2024, Sep 2023 | March | March 2025 = 1 Mar to 31 Mar 2025 (assumption stated) |
| | | December | December 2024 = 1 Dec to 31 Dec 2024 |
| `named_quarter` | Q1 2025, 2024 Q4, Q3, first quarter of 2024 | Q3 | Q3 2024 = 1 Jul to 30 Sep 2024 (assumption stated) |
| `named_year` | 2024, in 2023 | 2024 | 2024 = 1 Jan to 31 Dec 2024 |
| | | 2025 | 2025 = 1 Jan to 6 May 2025 (to date) |
| `named_fiscal_year` | FY2024, fiscal year 2024 | FY2024 | FY2024 = 1 Jan to 31 Dec 2024 |
| `explicit_range` | from A to B, between A and B, A until / through B | between 1 Jan 2024 and 31 Mar 2024 | Selected range = 1 Jan to 31 Mar 2024 |
| `explicit_date` | 2025-02-14, on 14 Feb 2025, February 14, 2025 | on 2025-02-14 | 14 Feb 2025 = 14 Feb 2025 |

Dates in explicit ranges can be written as `2024-01-31`, `31 Jan 2024` or
`January 31, 2024`. Slash dates (`01/02/2024`) are not accepted because day and month order
is ambiguous.

## Unresolved examples

| Phrase | Reason given |
| --- | --- |
| (empty) | no time period given |
| someday, recently, next month | not recognised; please give a month, quarter, year or a date range |
| June 2025 | starts after business today; there is no data yet |
| from 2024-03-31 to 2024-01-01 | start date is after the end date |
| 2024-02-30, Q5 2024 | not a valid date or quarter |

## Boundaries covered by tests

`tests/unit/test_calendar.py` checks every phrase above plus:
- the first and last day of a quarter (1 Apr and 31 Mar), and the year boundary (1 Jan);
- leap years (29 Feb 2024 versus 28 Feb 2025, "last 30 days" across February);
- week start Monday versus Sunday on a Sunday reference date;
- a fiscal year starting in April;
- the brief's example date 2025-12-31 ("last quarter" = 1 Jul to 30 Sep 2025, the last
  complete quarter, and "this quarter" = 1 Oct to 31 Dec 2025);
- a changed reference date in the config file.
