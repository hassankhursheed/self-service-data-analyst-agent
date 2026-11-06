"""The Docker Compose database has the original Northwind data loaded."""

import psycopg
import pytest

from app.db.northwind import EXPECTED_ROW_COUNTS, NORTHWIND_TABLES, existing_tables, row_counts

pytestmark = pytest.mark.integration


def test_all_14_northwind_tables_exist(owner_conn: psycopg.Connection) -> None:
    assert len(NORTHWIND_TABLES) == 14
    assert set(NORTHWIND_TABLES) <= existing_tables(owner_conn)


def test_row_counts_match_the_source_dump(owner_conn: psycopg.Connection) -> None:
    counts = row_counts(owner_conn)
    assert counts == dict(EXPECTED_ROW_COUNTS)
    non_empty = [
        t for t in NORTHWIND_TABLES if t not in {"customer_customer_demo", "customer_demographics"}
    ]
    assert all(counts[t] > 0 for t in non_empty)
