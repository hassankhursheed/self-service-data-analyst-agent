"""Operational health metrics for the admin Monitoring page (brief §26).

All numbers are SQL aggregations over the audit tables (app role) for one period of
calendar days in the monitoring time zone (config/app.yaml ``monitoring``):

- Questions and outcomes come from ``app.questions`` (created in the period, current
  status); a question paused for a clarification counts as ``awaiting_clarification``.
- Latency, tokens, cost and repairs come from ``app.agent_runs`` (runs started in the
  period). A run is written when a question finishes, so a paused question has none yet.
- p95 latency uses PostgreSQL ``percentile_cont(0.95)``: linear interpolation between the
  two nearest ranks (the same definition as numpy's default). See ``p95``.
- Repair success rate = runs with at least one repair that ended ANSWERED / runs with at
  least one repair.
"""

import datetime as dt
import math
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import MonitoringConfig
from app.core.errors import AppError

OUTCOMES = {
    "ANSWERED": "answered",
    "BLOCKED": "blocked",
    "REJECTED": "rejected",
    "FAILED": "failed",
}


class InvalidPeriod(AppError):
    code = "VALIDATION_ERROR"
    user_message = "Choose a valid period."


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class OutcomeCounts(_Frozen):
    answered: int = 0
    blocked: int = 0
    rejected: int = 0
    failed: int = 0
    awaiting_clarification: int = 0
    in_progress: int = 0


class FeedbackCounts(_Frozen):
    helpful: int = 0
    not_helpful: int = 0


class EvalRunSummary(_Frozen):
    run_id: uuid.UUID
    experiment_name: str
    status: str
    execution_accuracy: Decimal | None
    unsafe_blocked_rate: Decimal | None
    access_leaks: int | None
    started_at: dt.datetime


class DailyPoint(_Frozen):
    date: dt.date
    questions: int
    answered: int
    blocked: int
    rejected: int
    failed: int
    cost_usd: Decimal


class Metrics(_Frozen):
    period_from: dt.date
    period_to: dt.date
    time_zone: str
    questions: int
    questions_by_role: dict[str, int]
    outcomes: OutcomeCounts
    blocked_by_reason: dict[str, int]
    repair_attempts: int
    repaired_runs: int
    repair_success_rate: float | None
    clarifications_asked: int
    runs: int
    latency_avg_ms: float | None
    latency_p95_ms: float | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    feedback: FeedbackCounts
    failed_logins: int
    latest_eval_run: EvalRunSummary | None
    daily: list[DailyPoint]


def p95(values: Sequence[float]) -> float | None:
    """95th percentile with linear interpolation (PostgreSQL percentile_cont, numpy default).

    Kept in Python for documentation and tests; the API computes it in SQL."""
    if not values:
        return None
    ordered = sorted(values)
    position = 0.95 * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


_QUERIES: dict[str, str] = {
    "questions": """
        SELECT COALESCE(role_name, 'no_role') AS role, status, count(*) AS n
        FROM app.questions
        WHERE created_at >= :start AND created_at < :end
        GROUP BY 1, 2
    """,
    "runs": """
        SELECT count(*) AS runs,
               avg(total_latency_ms) AS latency_avg,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS latency_p95,
               COALESCE(sum(input_tokens), 0) AS input_tokens,
               COALESCE(sum(output_tokens), 0) AS output_tokens,
               COALESCE(sum(estimated_cost_usd), 0) AS cost
        FROM app.agent_runs
        WHERE started_at >= :start AND started_at < :end AND total_latency_ms IS NOT NULL
    """,
    "blocked": """
        SELECT reason_code, count(*) AS n FROM app.blocked_queries
        WHERE created_at >= :start AND created_at < :end
        GROUP BY reason_code ORDER BY n DESC, reason_code
    """,
    "repairs": """
        SELECT count(g.id) AS attempts,
               count(DISTINCT r.id) AS repaired_runs,
               count(DISTINCT r.id) FILTER (WHERE r.final_status = 'ANSWERED') AS repaired_answered
        FROM app.agent_runs r
        JOIN app.generated_queries g ON g.run_id = r.id AND g.kind = 'repair'
        WHERE r.started_at >= :start AND r.started_at < :end
    """,
    "clarifications": """
        SELECT count(*) FROM app.clarifications
        WHERE created_at >= :start AND created_at < :end
    """,
    "feedback": """
        SELECT rating, count(*) AS n FROM app.feedback
        WHERE updated_at >= :start AND updated_at < :end GROUP BY rating
    """,
    "failed_logins": """
        SELECT count(*) FROM app.audit_log
        WHERE event_type = 'login_failed' AND occurred_at >= :start AND occurred_at < :end
    """,
    "latest_eval": """
        SELECT id, experiment_name, status, execution_accuracy, unsafe_blocked_rate,
               access_leaks, started_at
        FROM app.eval_runs ORDER BY started_at DESC LIMIT 1
    """,
    "daily_questions": """
        SELECT (created_at AT TIME ZONE :tz)::date AS day, status, count(*) AS n
        FROM app.questions
        WHERE created_at >= :start AND created_at < :end
        GROUP BY 1, 2
    """,
    "daily_cost": """
        SELECT (started_at AT TIME ZONE :tz)::date AS day,
               COALESCE(sum(estimated_cost_usd), 0) AS cost
        FROM app.agent_runs
        WHERE started_at >= :start AND started_at < :end
        GROUP BY 1
    """,
}


class MetricsService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], config: MonitoringConfig
    ) -> None:
        self.sessions = sessions
        self.config = config

    def period(
        self, date_from: dt.date | None, date_to: dt.date | None, today: dt.date | None = None
    ) -> tuple[dt.date, dt.date, dt.datetime, dt.datetime]:
        zone = ZoneInfo(self.config.time_zone)
        today = today or dt.datetime.now(zone).date()
        first = date_from or date_to or today
        last = date_to or (date_from if date_from else today)
        if last < first:
            raise InvalidPeriod(f"{first} > {last}", user_message="'From' must not be after 'to'.")
        if (last - first).days + 1 > self.config.max_period_days:
            raise InvalidPeriod(
                "period too long",
                user_message=f"Choose at most {self.config.max_period_days} days.",
            )
        start = dt.datetime.combine(first, dt.time.min, tzinfo=zone)
        end = dt.datetime.combine(last + dt.timedelta(days=1), dt.time.min, tzinfo=zone)
        return first, last, start, end

    async def metrics(
        self, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> Metrics:
        first, last, start, end = self.period(date_from, date_to)
        params: dict[str, Any] = {"start": start, "end": end, "tz": self.config.time_zone}
        async with self.sessions() as session:
            rows = {
                name: (await session.execute(text(sql), params)).all()
                for name, sql in _QUERIES.items()
            }
        return self._build(first, last, rows)

    def _build(self, first: dt.date, last: dt.date, rows: dict[str, Any]) -> Metrics:
        by_role: dict[str, int] = {}
        outcomes: dict[str, int] = {}
        for role, status, n in rows["questions"]:
            by_role[role] = by_role.get(role, 0) + n
            key = OUTCOMES.get(
                status,
                "awaiting_clarification" if status == "CLARIFICATION_NEEDED" else "in_progress",
            )
            outcomes[key] = outcomes.get(key, 0) + n
        runs = rows["runs"][0]
        attempts, repaired, repaired_answered = rows["repairs"][0]
        feedback = dict(rows["feedback"])
        latest = rows["latest_eval"][0] if rows["latest_eval"] else None

        days: dict[dt.date, dict[str, Any]] = {}
        for offset in range((last - first).days + 1):
            day = first + dt.timedelta(days=offset)
            days[day] = {"date": day, "questions": 0, "answered": 0, "blocked": 0,
                         "rejected": 0, "failed": 0, "cost_usd": Decimal(0)}  # fmt: skip
        for day, status, n in rows["daily_questions"]:
            if day in days:
                days[day]["questions"] += n
                if status in OUTCOMES:
                    days[day][OUTCOMES[status]] += n
        for day, cost in rows["daily_cost"]:
            if day in days:
                days[day]["cost_usd"] = Decimal(cost)

        return Metrics(
            period_from=first,
            period_to=last,
            time_zone=self.config.time_zone,
            questions=sum(by_role.values()),
            questions_by_role=dict(sorted(by_role.items())),
            outcomes=OutcomeCounts(**outcomes),
            blocked_by_reason=dict(rows["blocked"]),
            repair_attempts=attempts,
            repaired_runs=repaired,
            repair_success_rate=round(repaired_answered / repaired, 4) if repaired else None,
            clarifications_asked=rows["clarifications"][0][0],
            runs=runs.runs,
            latency_avg_ms=round(float(runs.latency_avg), 1)
            if runs.latency_avg is not None
            else None,
            latency_p95_ms=round(float(runs.latency_p95), 1)
            if runs.latency_p95 is not None
            else None,
            input_tokens=int(runs.input_tokens),
            output_tokens=int(runs.output_tokens),
            cost_usd=Decimal(runs.cost),
            feedback=FeedbackCounts(
                helpful=feedback.get("helpful", 0), not_helpful=feedback.get("not_helpful", 0)
            ),
            failed_logins=rows["failed_logins"][0][0],
            latest_eval_run=EvalRunSummary(
                run_id=latest.id,
                experiment_name=latest.experiment_name,
                status=latest.status,
                execution_accuracy=latest.execution_accuracy,
                unsafe_blocked_rate=latest.unsafe_blocked_rate,
                access_leaks=latest.access_leaks,
                started_at=latest.started_at,
            )
            if latest
            else None,
            daily=[DailyPoint(**values) for values in days.values()],
        )
