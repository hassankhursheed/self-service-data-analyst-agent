"""Read-only facts about the Northwind source tables (public schema)."""

from collections.abc import Mapping

import psycopg
from psycopg import sql

NORTHWIND_SCHEMA = "public"

# Row counts in data/northwind/northwind.sql. The two customer-demographics tables are
# empty in the public dump.
EXPECTED_ROW_COUNTS: Mapping[str, int] = {
    "categories": 8,
    "customer_customer_demo": 0,
    "customer_demographics": 0,
    "customers": 91,
    "employee_territories": 49,
    "employees": 9,
    "order_details": 2155,
    "orders": 830,
    "products": 77,
    "region": 4,
    "shippers": 6,
    "suppliers": 29,
    "territories": 53,
    "us_states": 51,
}
NORTHWIND_TABLES: tuple[str, ...] = tuple(sorted(EXPECTED_ROW_COUNTS))


def existing_tables(conn: psycopg.Connection) -> set[str]:
    """Return the base tables present in the Northwind schema."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
        (NORTHWIND_SCHEMA,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def row_counts(conn: psycopg.Connection) -> dict[str, int]:
    """Count rows in every Northwind table (read-only)."""
    counts: dict[str, int] = {}
    for table in NORTHWIND_TABLES:
        query = sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier(NORTHWIND_SCHEMA), sql.Identifier(table)
        )
        row = conn.execute(query).fetchone()
        counts[table] = int(row[0]) if row else 0
    return counts
