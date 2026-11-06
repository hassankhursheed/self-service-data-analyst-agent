"""Load the semantic layer YAML, sync it into the database, and read it back.

The YAML file is the versioned source. ``sync_semantic_layer`` copies it into
``app.semantic_catalog`` and ``app.metric_definitions`` (safe to run twice);
``load_active_semantic_layer`` rebuilds the model from the active database rows, which is
what the agent retrieves from.
"""

from pathlib import Path
from typing import Any

import psycopg

from app.core.config import PROJECT_ROOT
from app.core.yaml_config import load_yaml_model
from app.semantic.models import SemanticLayer

SEMANTIC_LAYER_FILE = PROJECT_ROOT / "config" / "semantic" / "semantic_layer.yaml"


def load_semantic_layer_file(path: Path = SEMANTIC_LAYER_FILE) -> SemanticLayer:
    return load_yaml_model(path, SemanticLayer)


def _catalog_rows(layer: SemanticLayer) -> list[tuple[str, str, str, list[str], list[str]]]:
    """(object_type, object_name, description, example_values, allowed_roles)."""
    rows: list[tuple[str, str, str, list[str], list[str]]] = []
    for t_name, table in layer.tables.items():
        rows.append(
            ("table", t_name, table.description, [], [r.value for r in table.allowed_roles])
        )
        for c_name, col in table.columns.items():
            rows.append(
                (
                    "column",
                    f"{t_name}.{c_name}",
                    col.description,
                    list(col.examples),
                    [r.value for r in col.allowed_roles],
                )
            )
    for join in layer.joins:
        rows.append(("join", join.key, join.condition, [], []))
    for term, target in layer.synonyms.items():
        rows.append(("synonym", term, target, [], []))
    return rows


def sync_semantic_layer(conn: psycopg.Connection, layer: SemanticLayer) -> dict[str, int]:
    """Make the YAML version the only active version in the database."""
    rows = _catalog_rows(layer)
    v = layer.version
    with conn.transaction():
        conn.execute(
            "UPDATE app.semantic_catalog SET is_active = false WHERE version <> %s AND is_active",
            (v,),
        )
        conn.execute(
            "UPDATE app.metric_definitions SET is_active = false WHERE version <> %s AND is_active",
            (v,),
        )
        keys = [f"{r[0]}|{r[1]}" for r in rows]
        conn.execute(
            "DELETE FROM app.semantic_catalog WHERE version = %s "
            "AND NOT ((object_type || '|' || object_name) = ANY(%s))",
            (v, keys),
        )
        conn.execute(
            "DELETE FROM app.metric_definitions WHERE version = %s AND NOT (name = ANY(%s))",
            (v, list(layer.metrics)),
        )
        for object_type, name, description, examples, roles in rows:
            conn.execute(
                "INSERT INTO app.semantic_catalog (object_type, object_name, description, "
                "example_values, allowed_roles, version, is_active) "
                "VALUES (%s, %s, %s, %s, %s, %s, true) "
                "ON CONFLICT (object_type, object_name, version) DO UPDATE SET "
                "description = EXCLUDED.description, example_values = EXCLUDED.example_values, "
                "allowed_roles = EXCLUDED.allowed_roles, is_active = true, updated_at = now()",
                (object_type, name, description, examples, roles, v),
            )
        for name, metric in layer.metrics.items():
            conn.execute(
                "INSERT INTO app.metric_definitions (name, description, definition_sql, tables, "
                "join_condition, synonyms, allowed_roles, version, is_active) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true) "
                "ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, "
                "definition_sql = EXCLUDED.definition_sql, tables = EXCLUDED.tables, "
                "join_condition = EXCLUDED.join_condition, synonyms = EXCLUDED.synonyms, "
                "allowed_roles = EXCLUDED.allowed_roles, is_active = true, updated_at = now()",
                (
                    name,
                    metric.description,
                    metric.definition,
                    metric.tables,
                    metric.join,
                    metric.synonyms,
                    [r.value for r in metric.allowed_roles],
                    v,
                ),
            )
    return {"version": v, "catalog_rows": len(rows), "metrics": len(layer.metrics)}


def load_active_semantic_layer(conn: psycopg.Connection) -> SemanticLayer:
    """Rebuild the semantic layer from the active rows in the database."""
    catalog = conn.execute(
        "SELECT object_type, object_name, description, example_values, allowed_roles, version "
        "FROM app.semantic_catalog WHERE is_active ORDER BY id"
    ).fetchall()
    metrics = conn.execute(
        "SELECT name, description, definition_sql, tables, join_condition, synonyms, "
        "allowed_roles FROM app.metric_definitions WHERE is_active ORDER BY id"
    ).fetchall()
    if not catalog:
        raise LookupError("no active semantic layer in the database; run the seed script")
    tables: dict[str, dict[str, Any]] = {}
    joins: list[dict[str, str]] = []
    synonyms: dict[str, str] = {}
    versions = {int(r[5]) for r in catalog}
    for object_type, name, description, examples, roles, _ in catalog:
        if object_type == "table":
            tables.setdefault(name, {"columns": {}}).update(
                description=description, allowed_roles=roles
            )
        elif object_type == "column":
            t_name, _, c_name = name.partition(".")
            tables.setdefault(t_name, {"columns": {}})["columns"][c_name] = {
                "description": description,
                "examples": examples,
                "allowed_roles": roles,
            }
        elif object_type == "join":
            left, _, right = name.partition("->")
            joins.append({"left": left, "right": right, "condition": description})
        elif object_type == "synonym":
            synonyms[name] = description
    return SemanticLayer.model_validate(
        {
            "version": max(versions),
            "tables": tables,
            "joins": joins,
            "metrics": {
                name: {
                    "description": description,
                    "definition": definition,
                    "tables": tbls,
                    "join": join,
                    "synonyms": syns,
                    "allowed_roles": roles,
                }
                for name, description, definition, tbls, join, syns, roles in metrics
            },
            "synonyms": synonyms,
        }
    )
