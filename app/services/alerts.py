"""Alerts when monitoring numbers pass their thresholds (recommended extra, brief §26).

Every ``check_every_seconds`` the API measures, over the last ``window_minutes``:

- ``failure_rate``: share of finished questions that FAILED (only with enough questions),
- ``blocked_attempts``: blocked queries,
- ``failed_logins``: failed logins,
- ``daily_cost``: estimated LLM cost since 00:00 UTC.

A value above its threshold creates one row in ``app.alerts`` (at most one per type per
``cooldown_minutes``), is logged as a warning and, when a Slack webhook URL is set, sent to
Slack. Sending never breaks the check: a failed post leaves ``sent_at`` empty.
"""

import asyncio
import contextlib
import datetime as dt
import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal
from enum import StrEnum

import httpx
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import AlertsConfig
from app.core.enums import AlertChannel
from app.db.models import Alert

logger = logging.getLogger(__name__)

Poster = Callable[[str, dict[str, str]], Awaitable[None]]
Clock = Callable[[], dt.datetime]


class AlertType(StrEnum):
    FAILURE_RATE = "failure_rate"
    BLOCKED_ATTEMPTS = "blocked_attempts"
    FAILED_LOGINS = "failed_logins"
    DAILY_COST = "daily_cost"


class AlertInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    alert_type: str
    metric_value: Decimal
    threshold: Decimal
    message: str
    channel: str
    sent_at: dt.datetime | None
    created_at: dt.datetime


_MEASURES = text("""
    SELECT
      (SELECT count(*) FROM app.questions
        WHERE created_at >= :since AND status IN ('ANSWERED', 'BLOCKED', 'REJECTED', 'FAILED'))
        AS finished,
      (SELECT count(*) FROM app.questions WHERE created_at >= :since AND status = 'FAILED')
        AS failed,
      (SELECT count(*) FROM app.blocked_queries WHERE created_at >= :since) AS blocked,
      (SELECT count(*) FROM app.audit_log
        WHERE event_type = 'login_failed' AND occurred_at >= :since) AS failed_logins,
      (SELECT COALESCE(sum(estimated_cost_usd), 0) FROM app.agent_runs
        WHERE started_at >= :day_start) AS cost_today
""")


async def post_to_slack(url: str, payload: dict[str, str]) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class AlertService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        config: AlertsConfig,
        *,
        slack_webhook_url: str | None = None,
        poster: Poster = post_to_slack,
        clock: Clock = _utc_now,
    ) -> None:
        self.sessions = sessions
        self.config = config
        self.slack_webhook_url = slack_webhook_url or None
        self.poster = poster
        self.clock = clock
        self._task: asyncio.Task[None] | None = None

    async def measure(self) -> dict[AlertType, tuple[Decimal, Decimal]]:
        """Current value and threshold of every check that has enough data."""
        now = self.clock()
        since = now - dt.timedelta(minutes=self.config.window_minutes)
        day_start = dt.datetime.combine(now.date(), dt.time.min, tzinfo=dt.UTC)
        async with self.sessions() as session:
            row = (await session.execute(_MEASURES, {"since": since, "day_start": day_start})).one()
        limits = self.config.thresholds
        values: dict[AlertType, tuple[Decimal, Decimal]] = {
            AlertType.BLOCKED_ATTEMPTS: (Decimal(row.blocked), Decimal(limits.blocked_attempts)),
            AlertType.FAILED_LOGINS: (Decimal(row.failed_logins), Decimal(limits.failed_logins)),
            AlertType.DAILY_COST: (Decimal(row.cost_today), Decimal(str(limits.daily_cost_usd))),
        }
        if row.finished >= self.config.min_questions_for_failure_rate:
            rate = (Decimal(row.failed) / Decimal(row.finished)).quantize(Decimal("0.0001"))
            values[AlertType.FAILURE_RATE] = (rate, Decimal(str(limits.failure_rate)))
        return values

    def _message(self, kind: AlertType, value: Decimal, limit: Decimal) -> str:
        window = f"in the last {self.config.window_minutes} minutes"
        return {
            AlertType.FAILURE_RATE: f"{value:.0%} of questions failed {window} "
            f"(threshold {limit:.0%}).",
            AlertType.BLOCKED_ATTEMPTS: f"{value} queries were blocked {window} "
            f"(threshold {limit}).",
            AlertType.FAILED_LOGINS: f"{value} failed logins {window} (threshold {limit}).",
            AlertType.DAILY_COST: f"Estimated LLM cost today is ${value:.2f} "
            f"(threshold ${limit:.2f}).",
        }[kind]

    async def check(self) -> list[AlertInfo]:
        """Create (and send) an alert for every threshold passed outside its cooldown."""
        now = self.clock()
        quiet_since = now - dt.timedelta(minutes=self.config.cooldown_minutes)
        created: list[AlertInfo] = []
        for kind, (value, limit) in (await self.measure()).items():
            if value <= limit:
                continue
            async with self.sessions() as session, session.begin():
                recent = await session.scalar(
                    select(func.count())
                    .select_from(Alert)
                    .where(Alert.alert_type == kind.value, Alert.created_at >= quiet_since)
                )
                if recent:
                    continue
                alert = Alert(
                    alert_type=kind.value,
                    metric_value=value,
                    threshold=limit,
                    message=self._message(kind, value, limit),
                    channel=(AlertChannel.SLACK if self.slack_webhook_url else AlertChannel.LOG),
                    created_at=now,
                )
                session.add(alert)
            logger.warning("alert %s: %s", kind.value, alert.message)
            if self.slack_webhook_url:
                await self._send(alert)
            created.append(AlertInfo.model_validate(alert, from_attributes=True))
        return created

    async def _send(self, alert: Alert) -> None:
        url = self.slack_webhook_url
        if url is None:
            return
        try:
            await self.poster(url, {"text": f":warning: Northwind agent: {alert.message}"})
        except Exception as exc:  # any delivery problem is only logged
            logger.warning("alert %s not sent to Slack: %s", alert.id, type(exc).__name__)
            return
        async with self.sessions() as session, session.begin():
            stored = await session.get(Alert, alert.id)
            if stored is not None:
                stored.sent_at = self.clock()
                alert.sent_at = stored.sent_at

    async def recent(self, limit: int = 50) -> list[AlertInfo]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit)
            )
            return [AlertInfo.model_validate(a, from_attributes=True) for a in rows]

    # --- background loop (one API process, like the rate limits) ----------------------

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.check_every_seconds)
            try:
                await self.check()
            except Exception:  # a failed check must not stop the loop
                logger.exception("alert check failed")

    def start(self) -> None:
        if self.config.enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="alert-checks")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
