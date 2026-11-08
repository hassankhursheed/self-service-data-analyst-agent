"""Remove logs older than the retention period (recommended extra, brief §27).

Logs are the audit log, per-node agent steps, blocked-query records, alerts and agent
errors that are no longer open. Nothing references these rows, so removing them never
breaks a conversation. Conversations, questions, runs, feedback and evaluation results
are kept (they are the product's history, removed only by ``scripts.reset_demo``).
The Northwind data is never touched.
"""

import datetime as dt

import psycopg
from psycopg import sql
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings

# table -> (time column, extra condition)
LOG_TABLES: dict[str, tuple[str, str]] = {
    "audit_log": ("occurred_at", ""),
    "agent_steps": ("created_at", ""),
    "blocked_queries": ("created_at", ""),
    "alerts": ("created_at", ""),
    "agent_errors": ("created_at", " AND status <> 'open'"),  # open errors stay for review
}


class RetentionReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    applied: bool
    cutoff: dt.datetime
    counts: dict[str, int]


def _where(table: str) -> sql.Composed:
    column, extra = LOG_TABLES[table]
    return sql.SQL("FROM {}.{} WHERE {} < %(cutoff)s" + extra).format(
        sql.Identifier("app"), sql.Identifier(table), sql.Identifier(column)
    )


def clean_logs(
    settings: Settings,
    *,
    apply: bool,
    days: int | None = None,
    now: dt.datetime | None = None,
) -> RetentionReport:
    """Count (and with ``apply`` delete) log rows older than ``days`` in one transaction."""
    keep_days = days if days is not None else settings.retention.log_days
    if keep_days < 1:
        raise ValueError("retention must be at least one day")
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(days=keep_days)
    counts: dict[str, int] = {}
    with psycopg.connect(settings.owner_conninfo()) as conn:
        for table in LOG_TABLES:
            row = conn.execute(
                sql.SQL("SELECT count(*) ") + _where(table), {"cutoff": cutoff}
            ).fetchone()
            counts[table] = int(row[0]) if row else 0
            if apply:
                conn.execute(sql.SQL("DELETE ") + _where(table), {"cutoff": cutoff})
        if apply:
            conn.commit()
        else:
            conn.rollback()
    return RetentionReport(applied=apply, cutoff=cutoff, counts=counts)
