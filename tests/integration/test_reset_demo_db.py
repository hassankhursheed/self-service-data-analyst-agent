"""Step 25: the demo reset removes demo activity, restores the seed and never touches Northwind.

Runs in a throwaway database (its own Northwind copy, migrated and seeded), so the real
local data is not affected.
"""

import os
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from app.core.config import PROJECT_ROOT, Settings
from app.db.northwind import row_counts
from app.db.setup.reset_demo import reset_demo
from scripts.seed import run_seed

pytestmark = pytest.mark.integration
NORTHWIND_DUMP = PROJECT_ROOT / "data" / "northwind" / "northwind.sql"


def _url_for(url: SecretStr, database: str) -> SecretStr:
    return SecretStr(
        make_url(url.get_secret_value())
        .set(database=database)
        .render_as_string(hide_password=False)
    )


@pytest.fixture(scope="module")
def scratch(settings: Settings) -> Iterator[Settings]:
    """A seeded copy of the project database, dropped afterwards."""
    name = f"reset_test_{os.getpid()}"
    try:
        owner = psycopg.connect(settings.owner_conninfo(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL is not reachable")
    with owner:
        owner.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )
        owner.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(
                make_conninfo(settings.owner_conninfo(), dbname=name), autocommit=True
            ) as c:
                c.execute(NORTHWIND_DUMP.read_text("utf-8"))
            scratch_settings = settings.model_copy(
                update={
                    "postgres_db": name,
                    "app_database_url": _url_for(settings.app_database_url, name),
                    "analytics_database_url": _url_for(settings.analytics_database_url, name),
                }
            )
            run_seed(scratch_settings)
            yield scratch_settings
        finally:
            owner.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


def _demo_activity(conn: psycopg.Connection) -> None:
    finance = conn.execute("SELECT id FROM app.users WHERE username = 'finance'").fetchone()
    assert finance is not None
    conv = conn.execute(
        "INSERT INTO app.conversations (user_id, title) VALUES (%s, 'demo') RETURNING id",
        (finance[0],),
    ).fetchone()
    assert conv is not None
    conn.execute(
        "INSERT INTO app.questions (correlation_id, conversation_id, user_id, question_text, "
        "status) VALUES (gen_random_uuid(), %s, %s, 'demo question', 'ANSWERED')",
        (conv[0], finance[0]),
    )
    conn.execute("INSERT INTO app.audit_log (event_type, details) VALUES ('login', '{}')")
    conn.execute(
        "INSERT INTO app.users (username, password_hash, display_name) "
        "VALUES ('visitor.made.up', 'x', 'Visitor')"
    )
    conn.execute("UPDATE app.users SET is_active = false WHERE username = 'sales.europe'")
    conn.execute("UPDATE app.verified_queries SET is_active = false")


def test_dry_run_changes_nothing_and_reset_restores_the_seed(scratch: Settings) -> None:
    with psycopg.connect(scratch.owner_conninfo(), autocommit=True) as conn:
        _demo_activity(conn)
        northwind_before = row_counts(conn)

    dry = reset_demo(scratch, apply=False)
    assert not dry.applied
    assert dry.counts["conversations"] == 1
    assert dry.counts["questions"] == 1
    assert dry.removed_users == ["visitor.made.up"]
    with psycopg.connect(scratch.owner_conninfo()) as conn:
        assert conn.execute("SELECT count(*) FROM app.conversations").fetchone() == (1,)

    done = reset_demo(scratch, apply=True)
    assert done.applied
    with psycopg.connect(scratch.owner_conninfo()) as conn:
        for table in ("conversations", "questions", "agent_runs", "audit_log", "feedback"):
            assert conn.execute(f"SELECT count(*) FROM app.{table}").fetchone() == (0,), table  # noqa: S608
        assert conn.execute(
            "SELECT count(*) FROM app.users WHERE username = 'visitor.made.up'"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT is_active FROM app.users WHERE username = 'sales.europe'"
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE is_active) FROM app.verified_queries"
        ).fetchone() == (18, 18)
        assert row_counts(conn) == northwind_before  # Northwind untouched


def test_the_real_database_is_not_touched_by_the_scratch_reset(
    scratch: Settings, settings: Settings, owner_conn: psycopg.Connection
) -> None:
    assert scratch.postgres_db != settings.postgres_db
    assert "reset_test_" in scratch.app_database_url.get_secret_value()
    assert owner_conn.execute("SELECT current_database()").fetchone() == (settings.postgres_db,)
