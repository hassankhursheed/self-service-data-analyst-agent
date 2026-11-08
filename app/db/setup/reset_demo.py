"""Reset the demo to a clean, seeded state (Step 25, docs/deployment.md).

Removes everything people did in the demo, in one transaction, then runs the idempotent
seed again so the demo accounts, roles, regions and the verified library are back to their
seeded state. The Northwind data (schema ``public``) is never touched.

Removed: conversations and everything under them (questions, runs, steps, generated and
executed queries, blocked queries, clarifications, feedback), agent errors, the audit log,
alerts, LangGraph checkpoints, verified queries (re-seeded), evaluation cases made from
feedback, users that are not demo users and, unless kept, evaluation runs.
"""

from collections.abc import Callable

import psycopg
from psycopg import sql
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings
from app.db.setup.checkpoints import CHECKPOINT_SCHEMA
from app.db.setup.users import load_test_users

REVIEW_DATASET = "review-cases"


class ResetReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    applied: bool
    counts: dict[str, int]
    removed_users: list[str]


def _count(conn: psycopg.Connection, sql: str, params: tuple[object, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def _checkpoint_tables(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (CHECKPOINT_SCHEMA,),
    ).fetchall()
    return sorted(str(r[0]) for r in rows if str(r[0]) != "checkpoint_migrations")


def reset_demo(
    settings: Settings,
    *,
    apply: bool,
    keep_eval: bool = False,
    reseed: Callable[[Settings], object] | None = None,
) -> ResetReport:
    """Count (and with ``apply`` delete) demo activity, then re-seed."""
    demo_users = [u.username for u in load_test_users().users]
    with psycopg.connect(settings.owner_conninfo()) as conn:  # one transaction
        removed_users = [
            str(r[0])
            for r in conn.execute(
                "SELECT username FROM app.users WHERE NOT (username = ANY(%s)) ORDER BY username",
                (demo_users,),
            ).fetchall()
        ]
        counts = {
            "conversations": _count(conn, "SELECT count(*) FROM app.conversations"),
            "questions": _count(conn, "SELECT count(*) FROM app.questions"),
            "agent_runs": _count(conn, "SELECT count(*) FROM app.agent_runs"),
            "feedback": _count(conn, "SELECT count(*) FROM app.feedback"),
            "agent_errors": _count(conn, "SELECT count(*) FROM app.agent_errors"),
            "audit_log": _count(conn, "SELECT count(*) FROM app.audit_log"),
            "alerts": _count(conn, "SELECT count(*) FROM app.alerts"),
            "verified_queries": _count(conn, "SELECT count(*) FROM app.verified_queries"),
            "eval_runs": 0 if keep_eval else _count(conn, "SELECT count(*) FROM app.eval_runs"),
            "users_not_in_demo": len(removed_users),
        }
        if not apply:
            conn.rollback()
            return ResetReport(applied=False, counts=counts, removed_users=removed_users)

        conn.execute("DELETE FROM app.conversations")  # cascades to questions and below
        conn.execute("DELETE FROM app.agent_errors")
        conn.execute("DELETE FROM app.audit_log")
        conn.execute("DELETE FROM app.alerts")
        conn.execute("DELETE FROM app.verified_queries")  # re-seeded below
        if not keep_eval:
            conn.execute("DELETE FROM app.eval_runs")  # cascades to eval_results
        conn.execute(
            "DELETE FROM app.eval_datasets d WHERE d.name = %s "
            "AND NOT EXISTS (SELECT 1 FROM app.eval_runs r WHERE r.dataset_id = d.id)",
            (REVIEW_DATASET,),
        )
        conn.execute("DELETE FROM app.users WHERE NOT (username = ANY(%s))", (demo_users,))
        for table in _checkpoint_tables(conn):
            conn.execute(
                sql.SQL("DELETE FROM {}.{}").format(
                    sql.Identifier(CHECKPOINT_SCHEMA), sql.Identifier(table)
                )
            )
        conn.commit()

    if reseed is None:
        from scripts.seed import run_seed

        reseed = run_seed
    reseed(settings)  # demo passwords, roles, regions, active flags, verified library
    return ResetReport(applied=True, counts=counts, removed_users=removed_users)
