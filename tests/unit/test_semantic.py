"""Step 7 unit tests: semantic YAML validation and role-filtered retrieval (no database)."""

from pathlib import Path

import pytest
import yaml

from app.core.enums import RoleName
from app.core.yaml_config import ConfigFileError
from app.safety.access_policy import load_access_policy
from app.semantic.catalog import SEMANTIC_LAYER_FILE, load_semantic_layer_file
from app.semantic.models import SemanticLayer
from app.semantic.retriever import retrieve, tokenize

LAYER = load_semantic_layer_file()
BUSINESS_ROLES = [RoleName.SALES_MANAGER, RoleName.FINANCE_ANALYST, RoleName.OPERATIONS_MANAGER]


def _write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "semantic_layer.yaml"
    path.write_text(yaml.safe_dump(data), "utf-8")
    return path


def test_semantic_yaml_validates() -> None:
    assert LAYER.version >= 1
    required = {
        "revenue",
        "number_of_orders",
        "average_order_value",
        "discount_amount",
        "freight_cost",
        "units_sold",
        "late_shipments",
    }
    assert required <= set(LAYER.metrics)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda d: d.update(unexpected=1), "unexpected: Extra inputs are not permitted"),
        (lambda d: d["metrics"]["revenue"].pop("definition"), "metrics.revenue.definition"),
        (
            lambda d: d["joins"].append({"left": "orders", "right": "nope", "condition": "x"}),
            "unknown table 'nope'",
        ),
        (lambda d: d["synonyms"].update(clients="table:clients"), "unknown target"),
        (
            lambda d: d["tables"]["orders"]["columns"]["freight"].update(allowed_roles=["admin"]),
            "allows roles the table does not",
        ),
    ],
)
def test_broken_semantic_file_fails_with_a_clear_error(
    tmp_path: Path, change: object, expected: str
) -> None:
    data = yaml.safe_load(SEMANTIC_LAYER_FILE.read_text("utf-8"))
    change(data)  # type: ignore[operator]
    path = _write(tmp_path, data)
    with pytest.raises(ConfigFileError) as err:
        load_semantic_layer_file(path)
    assert str(path) in str(err.value)
    assert expected in str(err.value)


def test_invalid_yaml_syntax_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "semantic_layer.yaml"
    path.write_text("version: [1\n", "utf-8")
    with pytest.raises(ConfigFileError, match="invalid YAML"):
        load_semantic_layer_file(path)


def test_tokenize_singularises() -> None:
    assert tokenize("Top Clients by Sales!") == ["top", "client", "by", "sale"]


@pytest.mark.parametrize("role", [RoleName.SALES_MANAGER, RoleName.FINANCE_ANALYST])
def test_top_clients_by_sales_retrieves_customers_orders_lines_and_revenue(role: RoleName) -> None:
    context = retrieve("top clients by sales", role, LAYER)
    assert {"customers", "orders", "order_details"} <= set(context.table_names)
    assert "revenue" in context.metric_names
    joins = {j.key for j in context.joins}
    assert {"customers->orders", "orders->order_details"} <= joins


def test_operations_does_not_get_revenue() -> None:
    context = retrieve("top clients by sales", RoleName.OPERATIONS_MANAGER, LAYER)
    assert "revenue" not in context.metric_names
    assert "customers" in context.table_names


def test_join_path_adds_intermediate_tables() -> None:
    context = retrieve("revenue by category", RoleName.FINANCE_ANALYST, LAYER)
    assert {"categories", "products", "order_details", "orders"} <= set(context.table_names)


EVERYTHING = " ".join(
    [*LAYER.tables, *(c for t in LAYER.tables.values() for c in t.columns), *LAYER.metrics,
     *LAYER.synonyms]
).replace("_", " ")  # fmt: skip


@pytest.mark.parametrize("role", [*BUSINESS_ROLES, RoleName.ADMIN])
def test_a_role_never_receives_objects_it_may_not_use(role: RoleName) -> None:
    context = retrieve(EVERYTHING, role, LAYER)
    policy = load_access_policy()
    for table in context.tables:
        assert role in LAYER.tables[table.name].allowed_roles
        for column in table.columns:
            assert role in LAYER.tables[table.name].columns[column.name].allowed_roles
            assert policy.is_column_visible(role, table.name, column.name)
    for metric in context.metrics:
        assert role in LAYER.metrics[metric.name].allowed_roles
    if role is RoleName.ADMIN:
        assert context.tables == []
        assert context.metrics == []


def test_semantic_permissions_never_exceed_the_access_policy() -> None:
    policy = load_access_policy()
    for t_name, table in LAYER.tables.items():
        for role in table.allowed_roles:
            assert t_name in policy.tables_for(role), (t_name, role)
        for c_name, column in table.columns.items():
            for role in column.allowed_roles:
                assert policy.is_column_visible(role, t_name, c_name), (t_name, c_name, role)


def test_changing_a_definition_changes_retrieval(tmp_path: Path) -> None:
    data = LAYER.model_dump(mode="json")
    data["metrics"]["revenue"]["definition"] = "SUM(od.unit_price * od.quantity)"
    changed = SemanticLayer.model_validate(data)
    context = retrieve("sales last year", RoleName.FINANCE_ANALYST, changed)
    assert context.metrics[0].definition == "SUM(od.unit_price * od.quantity)"
