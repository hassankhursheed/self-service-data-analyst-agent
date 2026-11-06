"""Sync config/calendar.yaml into app.business_calendar_config (one active version)."""

import psycopg

from app.semantic.calendar import CalendarConfig


def sync_calendar(conn: psycopg.Connection, cal: CalendarConfig) -> int:
    """Make ``cal.version`` the only active calendar row; safe to run twice."""
    with conn.transaction():
        conn.execute(
            "UPDATE app.business_calendar_config SET is_active = false "
            "WHERE version <> %s AND is_active",
            (cal.version,),
        )
        conn.execute(
            "INSERT INTO app.business_calendar_config "
            "(version, reference_date, time_zone, fiscal_year_start_month, week_start, is_active) "
            "VALUES (%s, %s, %s, %s, %s, true) "
            "ON CONFLICT (version) DO UPDATE SET reference_date = EXCLUDED.reference_date, "
            "time_zone = EXCLUDED.time_zone, "
            "fiscal_year_start_month = EXCLUDED.fiscal_year_start_month, "
            "week_start = EXCLUDED.week_start, is_active = true",
            (
                cal.version,
                cal.reference_date,
                cal.time_zone,
                cal.fiscal_year_start_month,
                cal.week_start.value,
            ),
        )
    return cal.version


def load_active_calendar(conn: psycopg.Connection) -> CalendarConfig:
    row = conn.execute(
        "SELECT version, reference_date, time_zone, fiscal_year_start_month, week_start "
        "FROM app.business_calendar_config WHERE is_active"
    ).fetchone()
    if row is None:
        raise LookupError("no active business calendar; run the seed script")
    version, reference_date, time_zone, start_month, week_start = row
    return CalendarConfig(
        version=version,
        reference_date=reference_date,
        time_zone=time_zone,
        fiscal_year_start_month=start_month,
        week_start=week_start,
    )
