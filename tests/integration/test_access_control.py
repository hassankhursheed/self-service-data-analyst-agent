"""Step 6: PostgreSQL itself enforces roles, regions and hidden columns."""

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.context import UserContext
from app.core.enums import RegionCode, RoleName
from app.db.analytics import QueryResult, ReadonlyQueryError, run_readonly

pytestmark = pytest.mark.integration

SALES = {
    "sales.europe": RegionCode.EUROPE,
    "sales.americas": RegionCode.AMERICAS,
    "sales.other": RegionCode.ROW,
}
FINANCE = UserContext(username="finance", role=RoleName.FINANCE_ANALYST)
OPERATIONS = UserContext(username="operations", role=RoleName.OPERATIONS_MANAGER)


def _sales(username: str) -> UserContext:
    return UserContext(username=username, role=RoleName.SALES_MANAGER, region=SALES[username])


async def _run(engine: AsyncEngine, sql: str, ctx: UserContext) -> QueryResult:
    return await run_readonly(sql, ctx, timeout_ms=5000, row_limit=1000, engine=engine)


async def _scalar(engine: AsyncEngine, sql: str, ctx: UserContext) -> object:
    return (await _run(engine, sql, ctx)).rows[0][0]


@pytest.mark.parametrize("username", list(SALES))
async def test_sales_manager_sees_only_their_region(
    username: str, analytics_engine: AsyncEngine, owner_conn: psycopg.Connection
) -> None:
    region = SALES[username].value
    expected = owner_conn.execute(
        "SELECT count(*) FROM analytics.order_regions WHERE region_code = %s", (region,)
    ).fetchone()
    assert expected is not None
    ctx = _sales(username)
    assert await _scalar(analytics_engine, "SELECT count(*) FROM orders", ctx) == expected[0]
    countries = await _run(analytics_engine, "SELECT DISTINCT country FROM customers", ctx)
    allowed = {
        str(r[0])
        for r in owner_conn.execute(
            "SELECT country FROM analytics.country_region WHERE region_code = %s", (region,)
        ).fetchall()
    }
    assert {str(r[0]) for r in countries.rows} <= allowed
    lines = await _scalar(
        analytics_engine,
        "SELECT count(*) FROM order_details od "
        "WHERE od.order_id NOT IN (SELECT order_id FROM orders)",
        ctx,
    )
    assert lines == 0


async def test_region_totals_add_up_to_the_full_total(analytics_engine: AsyncEngine) -> None:
    revenue = (
        "SELECT count(DISTINCT o.order_id), round(sum(od.unit_price * od.quantity * "
        "(1 - od.discount))::numeric, 2) FROM orders o JOIN order_details od USING (order_id)"
    )
    total = (await _run(analytics_engine, revenue, FINANCE)).rows[0]
    parts = [(await _run(analytics_engine, revenue, _sales(u))).rows[0] for u in SALES]
    assert total[0] == 830
    assert sum(int(p[0]) for p in parts) == total[0]
    assert abs(sum(p[1] for p in parts) - total[1]) <= len(parts) * 0.01


async def test_finance_sees_all_orders_but_no_employee_personal_data(
    analytics_engine: AsyncEngine,
) -> None:
    assert await _scalar(analytics_engine, "SELECT count(*) FROM orders", FINANCE) == 830
    columns = (await _run(analytics_engine, "SELECT * FROM employees", FINANCE)).columns
    assert {"first_name", "last_name", "title"} <= set(columns)
    hidden = {"address", "home_phone", "birth_date", "notes", "photo", "photo_path", "city"}
    assert not hidden & set(columns)
    with pytest.raises(ReadonlyQueryError) as err:
        await _run(analytics_engine, "SELECT birth_date FROM employees", FINANCE)
    assert err.value.kind == "db_error"


async def test_operations_sees_products_suppliers_shipping_not_customer_contacts(
    analytics_engine: AsyncEngine,
) -> None:
    for table in ("products", "suppliers", "shippers", "orders"):
        query = f"SELECT count(*) FROM {table}"  # noqa: S608 (fixed table names)
        assert int(str(await _scalar(analytics_engine, query, OPERATIONS))) > 0
    customer_cols = (await _run(analytics_engine, "SELECT * FROM customers", OPERATIONS)).columns
    assert not {"contact_name", "contact_title", "phone", "fax", "address"} & set(customer_cols)
    supplier_cols = (await _run(analytics_engine, "SELECT * FROM suppliers", OPERATIONS)).columns
    assert "contact_name" in supplier_cols
    with pytest.raises(ReadonlyQueryError):
        await _run(analytics_engine, "SELECT contact_name, phone FROM customers", OPERATIONS)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO public.shippers (shipper_id, company_name) VALUES (99, 'x')",
        "UPDATE public.orders SET freight = 0",
        "DELETE FROM public.order_details",
        "INSERT INTO finance_ro.shippers (shipper_id, company_name) VALUES (99, 'x')",
        "CREATE TABLE public.evil (id int)",
        "CREATE TABLE finance_ro.evil (id int)",
        "CREATE TEMP TABLE evil (id int)",
        "CREATE FUNCTION finance_ro.f() RETURNS int LANGUAGE sql AS 'SELECT 1'",
        "SELECT * FROM app.users",
        "SELECT * FROM public.orders",
    ],
)
def test_analytics_ro_cannot_write_create_or_read_raw_and_app_data(
    statement: str, analytics_ro_conninfo: str
) -> None:
    with psycopg.connect(analytics_ro_conninfo, autocommit=True) as conn:
        # Even with read-only turned off for the session, privileges still block the statement.
        conn.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


def test_missing_session_settings_return_zero_rows(analytics_ro_conninfo: str) -> None:
    with psycopg.connect(analytics_ro_conninfo, autocommit=True) as conn:
        for schema in ("finance_ro", "operations_ro", "sales_ro"):
            row = conn.execute(f"SELECT count(*) FROM {schema}.orders").fetchone()  # noqa: S608
            assert row == (0,)
        # Role set but no region: sales views stay empty (fail closed).
        with conn.transaction():
            conn.execute("SET LOCAL app.user_role = 'sales_manager'")
            assert conn.execute("SELECT count(*) FROM sales_ro.orders").fetchone() == (0,)


async def test_query_cannot_change_its_own_region(analytics_engine: AsyncEngine) -> None:
    americas = _sales("sales.americas")
    own = await _scalar(analytics_engine, "SELECT count(*) FROM orders", americas)
    attempts = [
        "SELECT set_config('app.user_region', 'EUROPE', true)",
        "SELECT count(*) FROM orders WHERE set_config('app.user_region', 'EUROPE', true) <> ''",
        "SET app.user_region = 'EUROPE'; SELECT count(*) FROM orders",
        "SET LOCAL app.user_role = 'finance_analyst'; SELECT count(*) FROM orders",
    ]
    for sql in attempts:
        with pytest.raises(ReadonlyQueryError):
            await _run(analytics_engine, sql, americas)
    assert await _scalar(analytics_engine, "SELECT count(*) FROM orders", americas) == own


async def test_other_role_schemas_return_nothing(analytics_engine: AsyncEngine) -> None:
    europe = _sales("sales.europe")
    assert await _scalar(analytics_engine, "SELECT count(*) FROM finance_ro.orders", europe) == 0


async def test_admin_has_no_business_data_access(analytics_engine: AsyncEngine) -> None:
    admin = UserContext(username="admin", role=RoleName.ADMIN)
    with pytest.raises(ReadonlyQueryError) as err:
        await _run(analytics_engine, "SELECT 1", admin)
    assert err.value.kind == "no_data_access"


async def test_array_results_work_without_set_config(analytics_engine: AsyncEngine) -> None:
    """asyncpg introspects array types; it must not need the revoked set_config()."""
    result = await _run(
        analytics_engine,
        "SELECT array_agg(DISTINCT ship_via ORDER BY ship_via) AS shippers FROM orders",
        FINANCE,
    )
    assert result.rows[0][0] == [1, 2, 3]


async def test_row_limit_truncates_results(analytics_engine: AsyncEngine) -> None:
    result = await run_readonly(
        "SELECT order_id FROM orders ORDER BY order_id", FINANCE, 5000, 10, engine=analytics_engine
    )
    assert result.row_count == 10
    assert result.truncated is True


async def test_statement_timeout_is_enforced(analytics_engine: AsyncEngine) -> None:
    with pytest.raises(ReadonlyQueryError) as err:
        await run_readonly("SELECT pg_sleep(2)", FINANCE, 200, 10, engine=analytics_engine)
    assert err.value.kind == "timeout"
