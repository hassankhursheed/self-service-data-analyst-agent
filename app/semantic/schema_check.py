"""Check that every table, column and metric in the semantic layer exists in the database.

- ``check_semantic_schema`` (owner): tables, columns and every metric definition; used by
  the seed and by ``scripts/schema_check.py`` in CI.
- ``check_semantic_catalog`` (any role): tables and columns from ``pg_catalog``, which
  every role can read whatever its privileges; the API runs it at start-up (Step 24).
"""

import psycopg
from psycopg import sql

from app.semantic.models import SemanticLayer


def check_semantic_schema(conn: psycopg.Connection, layer: SemanticLayer) -> list[str]:
    """Return a list of problems; empty means the semantic layer matches the database."""
    problems: list[str] = []
    rows = conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    ).fetchall()
    existing: dict[str, set[str]] = {}
    for table, column in rows:
        existing.setdefault(str(table), set()).add(str(column))

    for t_name, table in layer.tables.items():
        if t_name not in existing:
            problems.append(f"table {t_name} does not exist")
            continue
        for c_name in table.columns:
            if c_name not in existing[t_name]:
                problems.append(f"column {t_name}.{c_name} does not exist")

    for m_name, metric in layer.metrics.items():
        from_clause = sql.SQL(", ").join(
            sql.SQL("public.{} {}").format(sql.Identifier(name), sql.Identifier(alias))
            for name, alias in (t.split() for t in metric.tables)
        )
        query = sql.SQL("SELECT {definition} FROM {from_clause} {where} LIMIT 0").format(
            definition=sql.SQL(metric.definition),
            from_clause=from_clause,
            where=sql.SQL("WHERE " + metric.join) if metric.join else sql.SQL(""),
        )
        try:
            with conn.transaction(force_rollback=True):
                conn.execute(query)
        except psycopg.Error as exc:
            problems.append(f"metric {m_name} does not run: {str(exc).strip()}")
    return problems


class SchemaDrift(Exception):
    """The database no longer matches the semantic layer (for example a renamed column)."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("semantic layer does not match the database: " + "; ".join(problems))
        self.problems = problems


def check_semantic_catalog(conn: psycopg.Connection, layer: SemanticLayer) -> list[str]:
    """Tables and columns of the semantic layer that are missing from ``public``.

    Reads pg_catalog, so it works for the application role, which has no privileges on
    the Northwind tables."""
    rows = conn.execute(
        "SELECT c.relname, a.attname FROM pg_catalog.pg_attribute a "
        "JOIN pg_catalog.pg_class c ON c.oid = a.attrelid "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v') "
        "AND a.attnum > 0 AND NOT a.attisdropped"
    ).fetchall()
    existing: dict[str, set[str]] = {}
    for table, column in rows:
        existing.setdefault(str(table), set()).add(str(column))
    problems: list[str] = []
    for t_name, table in layer.tables.items():
        if t_name not in existing:
            problems.append(f"table {t_name} does not exist")
            continue
        problems.extend(
            f"column {t_name}.{c_name} does not exist"
            for c_name in table.columns
            if c_name not in existing[t_name]
        )
    return problems
