"""Step 7: the semantic layer syncs into the database and drives retrieval."""

from pathlib import Path

import psycopg
import pytest
import yaml

from app.core.enums import RoleName
from app.semantic.catalog import (
    SEMANTIC_LAYER_FILE,
    load_active_semantic_layer,
    load_semantic_layer_file,
    sync_semantic_layer,
)
from app.semantic.models import SemanticLayer
from app.semantic.retriever import retrieve
from app.semantic.schema_check import check_semantic_schema
from scripts.seed import SeedSummary

pytestmark = pytest.mark.integration


def test_database_copy_matches_the_yaml(
    seeded: SeedSummary, owner_conn: psycopg.Connection
) -> None:
    assert load_active_semantic_layer(owner_conn) == load_semantic_layer_file()


def test_sync_twice_keeps_the_same_rows(
    seeded: SeedSummary, owner_conn: psycopg.Connection
) -> None:
    def count() -> tuple[object, ...]:
        row = owner_conn.execute(
            "SELECT (SELECT count(*) FROM app.semantic_catalog),"
            " (SELECT count(*) FROM app.metric_definitions)"
        ).fetchone()
        assert row is not None
        return tuple(row)

    before = count()
    sync_semantic_layer(owner_conn, load_semantic_layer_file())
    assert count() == before


def test_changed_revenue_definition_reaches_the_retriever_without_code_changes(
    seeded: SeedSummary, owner_conn: psycopg.Connection, tmp_path: Path
) -> None:
    data = yaml.safe_load(SEMANTIC_LAYER_FILE.read_text("utf-8"))
    new_definition = "SUM(od.unit_price * od.quantity)"
    data["metrics"]["revenue"]["definition"] = new_definition
    changed = tmp_path / "semantic_layer.yaml"
    changed.write_text(yaml.safe_dump(data), "utf-8")
    try:
        sync_semantic_layer(owner_conn, load_semantic_layer_file(changed))
        context = retrieve(
            "revenue by month", RoleName.FINANCE_ANALYST, load_active_semantic_layer(owner_conn)
        )
        assert [m.definition for m in context.metrics if m.name == "revenue"] == [new_definition]
    finally:
        sync_semantic_layer(owner_conn, load_semantic_layer_file())
    restored = retrieve(
        "revenue by month", RoleName.FINANCE_ANALYST, load_active_semantic_layer(owner_conn)
    )
    assert [m.definition for m in restored.metrics if m.name == "revenue"] != [new_definition]


def test_schema_check_passes_and_detects_missing_objects(
    seeded: SeedSummary, owner_conn: psycopg.Connection
) -> None:
    layer = load_semantic_layer_file()
    assert check_semantic_schema(owner_conn, layer) == []

    data = layer.model_dump(mode="json")
    data["tables"]["orders"]["columns"]["no_such_column"] = {
        "description": "x",
        "allowed_roles": ["finance_analyst"],
    }
    data["metrics"]["revenue"]["definition"] = "SUM(od.no_such_column)"
    broken = SemanticLayer.model_validate(data)
    problems = check_semantic_schema(owner_conn, broken)
    assert any("orders.no_such_column" in p for p in problems)
    assert any(p.startswith("metric revenue") for p in problems)
