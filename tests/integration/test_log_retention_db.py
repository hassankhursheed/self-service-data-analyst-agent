"""Step 26 extra: the clean-up job removes only logs past the retention period."""

import datetime as dt
import json
from collections.abc import Iterator

import psycopg
import pytest

from app.core.config import Settings
from app.db.setup.log_retention import clean_logs
from scripts.seed import SeedSummary

pytestmark = pytest.mark.integration
MARK = "retention-test"
OLD = dt.datetime.now(dt.UTC) - dt.timedelta(days=400)


@pytest.fixture
def old_and_new_logs(owner_conn: psycopg.Connection, seeded: SeedSummary) -> Iterator[None]:
    details = json.dumps({"test": MARK})
    owner_conn.execute(
        "INSERT INTO app.audit_log (event_type, details, occurred_at) VALUES "
        "('retention_old', %s, %s), ('retention_new', %s, now())",
        (details, OLD, details),
    )
    owner_conn.execute(
        "INSERT INTO app.alerts (alert_type, metric_value, threshold, message, created_at) "
        "VALUES ('retention_test', 1, 0, %s, %s)",
        (MARK, OLD),
    )
    yield
    owner_conn.execute("DELETE FROM app.audit_log WHERE details->>'test' = %s", (MARK,))
    owner_conn.execute("DELETE FROM app.alerts WHERE message = %s", (MARK,))


def count(conn: psycopg.Connection, query: str) -> int:
    row = conn.execute(query, (MARK,)).fetchone()
    return int(row[0]) if row else 0


AUDIT = "SELECT count(*) FROM app.audit_log WHERE details->>'test' = %s"
ALERTS = "SELECT count(*) FROM app.alerts WHERE message = %s"


def test_dry_run_counts_and_apply_removes_only_old_rows(
    settings: Settings, owner_conn: psycopg.Connection, old_and_new_logs: None
) -> None:
    # Only rows older than 399 days count, so real local logs are not affected.
    dry = clean_logs(settings, apply=False, days=399)
    assert not dry.applied
    assert dry.counts["audit_log"] >= 1
    assert dry.counts["alerts"] >= 1
    assert count(owner_conn, AUDIT) == 2  # nothing removed by the dry run

    done = clean_logs(settings, apply=True, days=399)
    assert done.applied
    assert count(owner_conn, AUDIT) == 1  # the recent entry stays
    assert count(owner_conn, ALERTS) == 0


def test_retention_must_be_positive(settings: Settings) -> None:
    with pytest.raises(ValueError, match="at least one day"):
        clean_logs(settings, apply=False, days=0)
