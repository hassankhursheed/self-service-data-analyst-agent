"""Step 25: the seed loads Northwind into an empty hosted database, and only there."""

import os
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.core.config import Settings
from app.db.northwind import EXPECTED_ROW_COUNTS, row_counts
from app.db.setup.northwind_data import SeedError
from app.db.setup.northwind_load import load_northwind_if_missing

pytestmark = pytest.mark.integration


@pytest.fixture
def empty_db(settings: Settings) -> Iterator[str]:
    name = f"nwload_test_{os.getpid()}"
    try:
        owner = psycopg.connect(settings.owner_conninfo(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL is not reachable")
    with owner:
        drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        owner.execute(drop)
        owner.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield make_conninfo(settings.owner_conninfo(), dbname=name)
        finally:
            owner.execute(drop)


def test_loads_once_into_an_empty_database(empty_db: str) -> None:
    with psycopg.connect(empty_db, autocommit=True) as conn:
        assert load_northwind_if_missing(conn) is True
        assert row_counts(conn) == dict(EXPECTED_ROW_COUNTS)
        assert load_northwind_if_missing(conn) is False  # already there: untouched
        assert row_counts(conn) == dict(EXPECTED_ROW_COUNTS)


def test_refuses_a_database_with_part_of_northwind(empty_db: str) -> None:
    with psycopg.connect(empty_db, autocommit=True) as conn:
        conn.execute("CREATE TABLE public.orders (order_id smallint)")
        with pytest.raises(SeedError, match="only part of Northwind"):
            load_northwind_if_missing(conn)
        assert conn.execute("SELECT count(*) FROM public.orders").fetchone() == (0,)


def test_the_project_database_is_left_alone(owner_conn: psycopg.Connection) -> None:
    assert load_northwind_if_missing(owner_conn) is False
