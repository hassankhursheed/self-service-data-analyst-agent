"""Step 9: SQL safety validator (pure unit tests; no database, no LLM)."""

import pytest

from app.core.enums import BlockReason, RoleName
from app.safety.question_check import validate_question
from app.safety.sql_policy import BLOCK_MESSAGES, load_sql_policy
from app.safety.sql_validator import SqlValidationResult, validate
from app.semantic.catalog import load_semantic_layer_file

LAYER = load_semantic_layer_file()
POLICY = load_sql_policy()
SALES, FINANCE, OPS = RoleName.SALES_MANAGER, RoleName.FINANCE_ANALYST, RoleName.OPERATIONS_MANAGER

REVENUE_BY_CATEGORY = """
SELECT c.category_name,
       ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) AS revenue
FROM orders o
JOIN order_details od ON od.order_id = o.order_id
JOIN products p ON p.product_id = od.product_id
JOIN categories c ON c.category_id = p.category_id
WHERE o.order_date BETWEEN '2024-01-01' AND '2024-12-31'
GROUP BY c.category_name
ORDER BY revenue DESC
"""


def check(sql: str, role: RoleName | None = FINANCE) -> SqlValidationResult:
    return validate(sql, role, LAYER, POLICY)


def blocked(sql: str, reason: BlockReason, role: RoleName | None = FINANCE) -> None:
    result = check(sql, role)
    assert result.allowed is False, f"expected {reason} for {sql!r}"
    assert result.reason_code is reason, (result.reason_code, result.detail)
    assert result.user_message == BLOCK_MESSAGES[reason]
    assert result.final_sql is None


def text(result: SqlValidationResult) -> str:
    """The final SQL of an allowed result."""
    assert result.final_sql is not None
    return result.final_sql


def allowed(sql: str, role: RoleName | None = FINANCE) -> SqlValidationResult:
    result = check(sql, role)
    assert result.allowed is True, (result.reason_code, result.detail)
    assert result.final_sql
    return result


# --- allowed queries --------------------------------------------------------------------------


def test_simple_count_is_allowed_and_gets_a_limit() -> None:
    result = allowed("SELECT count(*) FROM orders")
    assert result.tables == ["orders"]
    assert text(result).endswith("LIMIT 200")


def test_valid_multi_join_revenue_query() -> None:
    result = allowed(REVENUE_BY_CATEGORY)
    assert result.tables == ["categories", "order_details", "orders", "products"]
    assert {"order_details.unit_price", "categories.category_name", "orders.order_date"} <= set(
        result.columns
    )


def test_valid_cte_query() -> None:
    sql = """
    WITH monthly AS (
        SELECT date_trunc('month', o.order_date) AS month, count(*) AS orders
        FROM orders o GROUP BY 1
    )
    SELECT month, orders FROM monthly ORDER BY month
    """
    result = allowed(sql)
    assert result.tables == ["orders"]


def test_cte_with_window_function_top_n_per_group() -> None:
    sql = """
    WITH ranked AS (
        SELECT p.category_id, p.product_name,
               RANK() OVER (PARTITION BY p.category_id ORDER BY sum(od.quantity) DESC) AS rnk
        FROM products p JOIN order_details od ON od.product_id = p.product_id
        GROUP BY p.category_id, p.product_name
    )
    SELECT * FROM ranked WHERE rnk <= 3
    """
    allowed(sql)


def test_union_of_selects_is_allowed() -> None:
    allowed("SELECT customer_id FROM customers UNION SELECT customer_id FROM orders")


@pytest.mark.parametrize(
    "where",
    [
        "o.order_date >= '2024-01-01' AND o.customer_id = 'ALFKI'",
        "o.ship_country = 'Germany' OR o.ship_country = 'France'",
        "(o.freight > 10 AND o.freight < 50) OR NOT o.ship_via = 3",
        "o.order_date BETWEEN '2024-01-01' AND '2024-12-31' AND o.freight IS NOT NULL",
    ],
)
def test_and_or_conditions_are_allowed(where: str) -> None:
    """Regression: sqlglot models AND/OR as connector nodes; they are not functions."""
    allowed(f"SELECT count(*) FROM orders o WHERE {where}")  # noqa: S608 (validator input)


def test_subquery_in_where_is_allowed() -> None:
    allowed(
        "SELECT company_name FROM customers WHERE customer_id IN (SELECT customer_id FROM orders)"
    )


def test_date_functions_on_stored_dates_are_allowed() -> None:
    allowed(
        "SELECT EXTRACT(year FROM order_date) AS y, to_char(order_date, 'YYYY-MM') AS m, "
        "make_date(2025, 1, 1) AS d FROM orders"
    )


def test_select_star_is_expanded_to_allowed_columns_only() -> None:
    result = allowed("SELECT * FROM customers", OPS)
    assert "contact_name" not in text(result)
    assert "phone" not in text(result)
    assert "company_name" in text(result)
    assert "*" not in text(result)


def test_table_star_is_expanded_too() -> None:
    result = allowed(
        "SELECT c.* FROM customers c JOIN orders o ON o.customer_id = c.customer_id", OPS
    )
    assert "contact_name" not in text(result)
    assert "c.*" not in text(result)


def test_select_star_on_employees_never_includes_personal_data() -> None:
    result = allowed("SELECT * FROM employees")
    for hidden in ("birth_date", "home_phone", "address", "notes"):
        assert hidden not in text(result)


def test_sales_manager_may_use_customer_contact_columns() -> None:
    result = allowed("SELECT contact_name, phone FROM customers", SALES)
    assert "customers.contact_name" in result.columns


def test_comment_is_removed_from_the_final_sql() -> None:
    result = allowed("SELECT company_name FROM customers -- ; DROP TABLE orders")
    assert "DROP" not in text(result).upper()
    assert "--" not in text(result)


def test_semicolon_inside_a_string_is_just_text() -> None:
    result = allowed("SELECT count(*) FROM customers WHERE company_name = 'x; DROP TABLE orders'")
    assert result.tables == ["customers"]


# --- statement types --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("INSERT INTO shippers (shipper_id, company_name) VALUES (9, 'x')", BlockReason.WRITE_STATEMENT),  # noqa: E501
        ("UPDATE orders SET freight = 0", BlockReason.WRITE_STATEMENT),
        ("DELETE FROM orders", BlockReason.WRITE_STATEMENT),
        ("MERGE INTO orders o USING orders s ON o.order_id = s.order_id WHEN MATCHED THEN DELETE", BlockReason.WRITE_STATEMENT),  # noqa: E501
        ("WITH gone AS (DELETE FROM orders RETURNING *) SELECT count(*) FROM gone", BlockReason.WRITE_STATEMENT),  # noqa: E501
        ("CREATE TABLE evil (id int)", BlockReason.DDL_STATEMENT),
        ("DROP TABLE orders", BlockReason.DDL_STATEMENT),
        ("ALTER TABLE orders ADD COLUMN x int", BlockReason.DDL_STATEMENT),
        ("TRUNCATE orders", BlockReason.DDL_STATEMENT),
        ("CREATE VIEW v AS SELECT * FROM orders", BlockReason.DDL_STATEMENT),
        ("GRANT SELECT ON orders TO public", BlockReason.PERMISSION_STATEMENT),
        ("REVOKE SELECT ON orders FROM public", BlockReason.PERMISSION_STATEMENT),
        ("COPY orders TO '/tmp/orders.csv'", BlockReason.COPY_STATEMENT),
        ("COPY orders FROM PROGRAM 'curl http://evil'", BlockReason.COPY_STATEMENT),
        ("SET app.user_region = 'EUROPE'", BlockReason.SET_STATEMENT),
        ("SET LOCAL statement_timeout = 0", BlockReason.SET_STATEMENT),
        ("CALL refresh_everything()", BlockReason.PROCEDURE_CALL),
        ("DO $$ BEGIN PERFORM 1; END $$", BlockReason.PROCEDURE_CALL),
        ("EXPLAIN SELECT * FROM orders", BlockReason.NOT_SELECT),
        ("BEGIN", BlockReason.NOT_SELECT),
        ("SELECT * INTO copy_of_orders FROM orders", BlockReason.SELECT_INTO),
        ("SELECT order_id FROM orders FOR UPDATE", BlockReason.LOCKING_CLAUSE),
        ("SELECT order_id FROM orders FOR SHARE", BlockReason.LOCKING_CLAUSE),
    ],
)  # fmt: skip
def test_non_read_statements_are_blocked(sql: str, reason: BlockReason) -> None:
    blocked(sql, reason)


def test_multiple_statements_are_blocked() -> None:
    blocked("SELECT count(*) FROM orders; DELETE FROM orders", BlockReason.MULTIPLE_STATEMENTS)


def test_second_statement_hidden_after_a_comment_is_blocked() -> None:
    blocked(
        "SELECT count(*) FROM orders /* totals */; DROP TABLE orders -- cleanup",
        BlockReason.MULTIPLE_STATEMENTS,
    )


def test_unparseable_sql_is_blocked() -> None:
    blocked("SELEC count(*) FROM", BlockReason.PARSE_ERROR)


@pytest.mark.parametrize("sql", ["", "   ", ";"])
def test_empty_sql_is_blocked(sql: str) -> None:
    result = check(sql)
    assert result.allowed is False
    assert result.reason_code in {BlockReason.EMPTY_SQL, BlockReason.PARSE_ERROR}


# --- tables, schemas and system catalogs --------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM pg_catalog.pg_roles",
        "SELECT rolname FROM pg_roles",
        "SELECT table_name FROM information_schema.tables",
        "SELECT usename FROM pg_user",
        "SELECT * FROM pg_toast.pg_toast_1234",
        "SELECT 'pg_roles'::regclass",
        "SELECT CAST('orders' AS regclass)",
    ],
)
def test_system_catalogs_are_blocked(sql: str) -> None:
    blocked(sql, BlockReason.SYSTEM_CATALOG)


@pytest.mark.parametrize(
    "sql", ["SELECT count(*) FROM finance_ro.orders", "SELECT * FROM public.orders"]
)
def test_schema_qualified_tables_are_blocked(sql: str) -> None:
    blocked(sql, BlockReason.SCHEMA_QUALIFIED)


def test_table_outside_the_semantic_layer_is_blocked() -> None:
    blocked("SELECT * FROM territories", BlockReason.TABLE_NOT_ALLOWED)


def test_app_schema_tables_are_not_reachable() -> None:
    blocked("SELECT * FROM users", BlockReason.TABLE_NOT_ALLOWED)


# --- hidden columns ------------------------------------------------------------------------------


def test_hidden_column_used_directly_is_blocked() -> None:
    blocked("SELECT contact_name FROM customers", BlockReason.COLUMN_NOT_ALLOWED, OPS)


def test_hidden_column_through_an_alias_is_blocked() -> None:
    blocked(
        "SELECT x.who FROM (SELECT c.contact_name AS who FROM customers c) x",
        BlockReason.COLUMN_NOT_ALLOWED,
        OPS,
    )


def test_hidden_column_through_a_cte_is_blocked() -> None:
    blocked(
        "WITH people AS (SELECT phone FROM customers) SELECT * FROM people",
        BlockReason.COLUMN_NOT_ALLOWED,
        FINANCE,
    )


def test_hidden_column_in_where_or_order_by_is_blocked() -> None:
    blocked(
        "SELECT 1 FROM customers WHERE contact_name LIKE 'A%'", BlockReason.COLUMN_NOT_ALLOWED, OPS
    )
    blocked(
        "SELECT company_name FROM customers ORDER BY phone", BlockReason.COLUMN_NOT_ALLOWED, OPS
    )


def test_employee_personal_data_is_blocked_for_every_role() -> None:
    for role in (SALES, FINANCE, OPS):
        blocked("SELECT birth_date FROM employees", BlockReason.COLUMN_NOT_ALLOWED, role)
        blocked("SELECT upper(e.address) FROM employees e", BlockReason.COLUMN_NOT_ALLOWED, role)


def test_supplier_contacts_only_for_operations() -> None:
    allowed("SELECT contact_name FROM suppliers", OPS)
    blocked("SELECT contact_name FROM suppliers", BlockReason.COLUMN_NOT_ALLOWED, FINANCE)


# --- functions ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT set_config('app.user_region', 'EUROPE', true)",
        "SELECT count(*) FROM orders WHERE set_config('app.user_region', 'EUROPE', true) <> ''",
        "SELECT current_setting('app.user_region')",
        "SELECT pg_sleep(10)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(x int)",
        "SELECT version()",
        "SELECT * FROM generate_series(1, 1000000000)",
        "SELECT query_to_xml('SELECT * FROM orders', true, true, '')",
        "SELECT some_unknown_function(order_id) FROM orders",
    ],
)
def test_dangerous_or_unknown_functions_are_blocked(sql: str) -> None:
    result = check(sql)
    assert result.allowed is False
    assert result.reason_code is BlockReason.FORBIDDEN_FUNCTION, (result.reason_code, result.detail)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM orders WHERE order_date > now() - interval '30 days'",
        "SELECT count(*) FROM orders WHERE order_date = current_date",
        "SELECT CURRENT_TIMESTAMP",
        "SELECT age(order_date) FROM orders",
    ],
)
def test_real_current_date_functions_are_blocked(sql: str) -> None:
    blocked(sql, BlockReason.REAL_DATE_FUNCTION)


# --- LIMIT -------------------------------------------------------------------------------------


def test_missing_limit_gets_the_default() -> None:
    assert text(allowed("SELECT order_id FROM orders")).endswith(f"LIMIT {POLICY.default_limit}")


def test_limit_above_maximum_is_lowered() -> None:
    assert text(allowed("SELECT order_id FROM orders LIMIT 50000")).endswith(
        f"LIMIT {POLICY.max_limit}"
    )


def test_limit_within_range_is_kept() -> None:
    assert text(allowed("SELECT order_id FROM orders LIMIT 5")).endswith("LIMIT 5")


def test_limit_all_becomes_the_maximum() -> None:
    assert text(allowed("SELECT order_id FROM orders LIMIT ALL")).endswith(
        f"LIMIT {POLICY.max_limit}"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT order_id FROM orders LIMIT $1",
        "SELECT order_id FROM orders LIMIT 10 + 5",
        "SELECT order_id FROM orders FETCH FIRST 5 ROWS ONLY",
    ],
)
def test_non_numeric_limit_is_blocked(sql: str) -> None:
    blocked(sql, BlockReason.INVALID_LIMIT)


def test_inner_limit_is_kept_and_outer_limit_added() -> None:
    result = allowed("SELECT x.order_id FROM (SELECT order_id FROM orders LIMIT 3) x")
    assert "LIMIT 3" in text(result)
    assert text(result).endswith(f"LIMIT {POLICY.default_limit}")


def test_union_gets_one_outer_limit() -> None:
    result = allowed("SELECT customer_id FROM customers UNION SELECT customer_id FROM orders")
    assert text(result).endswith(f"LIMIT {POLICY.default_limit}")


# --- roles ------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", [RoleName.ADMIN, None])
def test_roles_without_business_data_are_blocked(role: RoleName | None) -> None:
    blocked("SELECT count(*) FROM orders", BlockReason.NO_DATA_ACCESS, role)


def test_role_metric_tables_follow_the_semantic_layer() -> None:
    # Operations can query orders and order lines (revenue metric is not offered to it by
    # retrieval, but the underlying columns are visible).
    allowed("SELECT sum(quantity) FROM order_details", OPS)


# --- question checks -----------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_question_is_rejected(text: str) -> None:
    result = validate_question(text, POLICY)
    assert (result.allowed, result.reason_code) == (False, BlockReason.QUESTION_EMPTY)


def test_too_long_question_is_rejected() -> None:
    result = validate_question("x" * (POLICY.max_question_length + 1), POLICY)
    assert (result.allowed, result.reason_code) == (False, BlockReason.QUESTION_TOO_LONG)


def test_normal_question_is_trimmed_and_allowed() -> None:
    result = validate_question("  How many orders last month?  ", POLICY)
    assert result.allowed is True
    assert result.question == "How many orders last month?"


def test_every_reason_code_has_a_user_message() -> None:
    assert set(BLOCK_MESSAGES) == set(BlockReason)
