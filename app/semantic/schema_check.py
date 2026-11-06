"""Check that every table, column and metric in the semantic layer exists in the database.

Used by the seed script now and by the schema-drift check later (Step 24).
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
