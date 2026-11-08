"""Step 26 extra: alert messages and the background loop."""

from decimal import Decimal
from typing import Any

from app.core.config import AlertsConfig
from app.services.alerts import AlertService, AlertType


def service(enabled: bool) -> AlertService:
    sessions: Any = None  # the loop does not touch the database before its first interval
    return AlertService(sessions, AlertsConfig(enabled=enabled, window_minutes=60))


def test_messages_are_plain_language() -> None:
    s = service(True)
    assert s._message(AlertType.FAILURE_RATE, Decimal("0.4"), Decimal("0.3")) == (
        "40% of questions failed in the last 60 minutes (threshold 30%)."
    )
    assert "$1.80" in s._message(AlertType.DAILY_COST, Decimal("1.8"), Decimal("1.5"))


async def test_the_loop_runs_only_when_enabled_and_stops_cleanly() -> None:
    off = service(False)
    off.start()
    assert off._task is None
    on = service(True)
    on.start()
    assert on._task is not None
    await on.stop()
    assert on._task is None
