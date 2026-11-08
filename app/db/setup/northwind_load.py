"""Load the public Northwind dump into an empty database (Step 25, hosted databases).

Locally the ``db`` container loads the dump on its first start. A hosted PostgreSQL
(Railway) starts empty, so the seed can load it once with ``--load-northwind``. The dump
is only loaded when none of the Northwind tables exist; a database with some of them is
refused, so existing data is never overwritten or mixed.
"""

from pathlib import Path

import psycopg

from app.core.config import PROJECT_ROOT
from app.db.northwind import NORTHWIND_TABLES, existing_tables
from app.db.setup.northwind_data import SeedError

NORTHWIND_DUMP = PROJECT_ROOT / "data" / "northwind" / "northwind.sql"


def load_northwind_if_missing(conn: psycopg.Connection, dump: Path = NORTHWIND_DUMP) -> bool:
    """Load the dump when no Northwind table exists. Returns True when it was loaded."""
    present = existing_tables(conn) & set(NORTHWIND_TABLES)
    if present == set(NORTHWIND_TABLES):
        return False
    if present:
        missing = sorted(set(NORTHWIND_TABLES) - present)
        raise SeedError(
            "the database has only part of Northwind (missing: "
            + ", ".join(missing)
            + "); refusing to load the dump over it"
        )
    if not dump.is_file():
        raise SeedError(f"Northwind dump not found: {dump}")
    conn.execute(dump.read_text("utf-8"))  # trusted local file shipped with the project
    return True
