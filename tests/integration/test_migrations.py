"""Alembic migrations create and remove the app schema without touching Northwind."""

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.core.config import PROJECT_ROOT, Settings
from app.db.models import APP_SCHEMA, Base
from app.db.northwind import row_counts
from app.db.session import create_app_engine

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def alembic_cfg() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


@pytest.fixture
def migrated(alembic_cfg: Config, owner_conn: psycopg.Connection) -> None:
    command.upgrade(alembic_cfg, "head")


def _app_tables(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (APP_SCHEMA,),
    ).fetchall()
    return {str(row[0]) for row in rows} - {"alembic_version"}


def test_upgrade_and_downgrade_leave_northwind_untouched(
    alembic_cfg: Config, owner_conn: psycopg.Connection
) -> None:
    northwind_before = row_counts(owner_conn)
    expected = {table.name for table in Base.metadata.sorted_tables}

    command.downgrade(alembic_cfg, "base")
    assert _app_tables(owner_conn) == set()

    command.upgrade(alembic_cfg, "head")
    assert _app_tables(owner_conn) == expected
    assert len(expected) == 24

    command.downgrade(alembic_cfg, "base")
    assert _app_tables(owner_conn) == set()
    assert row_counts(owner_conn) == northwind_before

    command.upgrade(alembic_cfg, "head")  # leave the database at head


def _insert_user(conn: psycopg.Connection, username: str) -> str:
    row = conn.execute(
        "INSERT INTO app.users (username, password_hash, display_name) "
        "VALUES (%s, 'not-a-real-hash', %s) RETURNING id",
        (username, username),
    ).fetchone()
    assert row is not None
    return str(row[0])


def _insert_role(conn: psycopg.Connection, name: str, db_role: str) -> int:
    row = conn.execute(
        "INSERT INTO app.roles (name, db_role) VALUES (%s, %s) RETURNING id", (name, db_role)
    ).fetchone()
    assert row is not None
    return int(row[0])


# Each test runs in a transaction that is always rolled back, so no rows are left behind.


def test_duplicate_username_is_rejected(migrated: None, owner_conn: psycopg.Connection) -> None:
    with owner_conn.transaction(force_rollback=True):
        _insert_user(owner_conn, "test.duplicate")
        with pytest.raises(psycopg.errors.UniqueViolation):
            _insert_user(owner_conn, "test.duplicate")


def test_question_status_must_be_an_allowed_value(
    migrated: None, owner_conn: psycopg.Connection
) -> None:
    with owner_conn.transaction(force_rollback=True):
        user_id = _insert_user(owner_conn, "test.status")
        conv = owner_conn.execute(
            "INSERT INTO app.conversations (user_id, title) VALUES (%s, 't') RETURNING id",
            (user_id,),
        ).fetchone()
        assert conv is not None
        with pytest.raises(psycopg.errors.CheckViolation):
            owner_conn.execute(
                "INSERT INTO app.questions (correlation_id, conversation_id, user_id, "
                "question_text, status) VALUES (gen_random_uuid(), %s, %s, 'q', 'NOT_A_STATUS')",
                (conv[0], user_id),
            )


def test_a_user_has_at_most_one_role(migrated: None, owner_conn: psycopg.Connection) -> None:
    with owner_conn.transaction(force_rollback=True):
        user_id = _insert_user(owner_conn, "test.roles")
        finance = _insert_role(owner_conn, "finance_analyst", "finance_ro")
        operations = _insert_role(owner_conn, "operations_manager", "operations_ro")
        sql = "INSERT INTO app.user_roles (user_id, role_id) VALUES (%s, %s)"
        owner_conn.execute(sql, (user_id, finance))
        with pytest.raises(psycopg.errors.UniqueViolation):
            owner_conn.execute(sql, (user_id, operations))


def test_sales_region_must_be_known(migrated: None, owner_conn: psycopg.Connection) -> None:
    with owner_conn.transaction(force_rollback=True):
        user_id = _insert_user(owner_conn, "test.region")
        with pytest.raises(psycopg.errors.CheckViolation):
            owner_conn.execute(
                "INSERT INTO app.user_regions (user_id, region_code) VALUES (%s, 'ASIA')",
                (user_id,),
            )


async def test_app_engine_connects_and_queries_the_app_schema(
    migrated: None, settings: Settings
) -> None:
    engine = create_app_engine(settings)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(select(Base.metadata.tables["app.users"].c.id).limit(1))
            assert result.all() is not None
    finally:
        await engine.dispose()
