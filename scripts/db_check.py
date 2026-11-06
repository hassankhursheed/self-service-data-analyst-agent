"""Connect to PostgreSQL and print the row count of every Northwind table.

Usage: python scripts/db_check.py
Exits with code 1 if the database is unreachable or a table is missing.
"""

import sys

import psycopg

from app.core.config import get_settings
from app.db.northwind import NORTHWIND_TABLES, existing_tables, row_counts


def main() -> int:
    settings = get_settings()
    try:
        conn = psycopg.connect(settings.owner_conninfo(), connect_timeout=5)
    except psycopg.OperationalError as exc:
        print(f"Cannot connect to PostgreSQL: {exc}", file=sys.stderr)
        return 1
    with conn:
        missing = sorted(set(NORTHWIND_TABLES) - existing_tables(conn))
        if missing:
            print(f"Missing Northwind tables: {', '.join(missing)}", file=sys.stderr)
            return 1
        counts = row_counts(conn)
    server = f"{settings.postgres_host}:{settings.postgres_port}"
    print(f"Northwind tables in {settings.postgres_db} ({server})")
    for table, count in counts.items():
        print(f"  {table:24s} {count:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
