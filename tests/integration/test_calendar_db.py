"""Step 8: the seed syncs config/calendar.yaml into app.business_calendar_config."""

import psycopg
import pytest

from app.semantic.calendar import load_calendar
from app.semantic.calendar_store import load_active_calendar, sync_calendar
from scripts.seed import SeedSummary

pytestmark = pytest.mark.integration


def test_active_calendar_row_matches_the_config(
    seeded: SeedSummary, owner_conn: psycopg.Connection
) -> None:
    assert load_active_calendar(owner_conn) == load_calendar()
    assert seeded.reference_date == "2025-05-06"


def test_calendar_sync_is_idempotent(seeded: SeedSummary, owner_conn: psycopg.Connection) -> None:
    sync_calendar(owner_conn, load_calendar())
    row = owner_conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE is_active) FROM app.business_calendar_config"
    ).fetchone()
    assert row == (1, 1)
