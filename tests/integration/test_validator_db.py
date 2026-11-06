"""Step 9: SQL that passes the validator runs through the read-only role (both layers)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.context import UserContext
from app.core.enums import RegionCode, RoleName
from app.db.analytics import ReadonlyQueryError, run_readonly
from app.safety.sql_validator import validate
from app.semantic.catalog import load_semantic_layer_file

pytestmark = pytest.mark.integration

LAYER = load_semantic_layer_file()


async def test_validated_revenue_query_runs_for_finance(analytics_engine: AsyncEngine) -> None:
    sql = (
        "SELECT c.category_name, SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue "
        "FROM orders o JOIN order_details od ON od.order_id = o.order_id "
        "JOIN products p ON p.product_id = od.product_id "
        "JOIN categories c ON c.category_id = p.category_id "
        "WHERE o.order_date BETWEEN '2024-01-01' AND '2024-12-31' GROUP BY 1 ORDER BY 2 DESC"
    )
    result = validate(sql, RoleName.FINANCE_ANALYST, LAYER)
    assert result.allowed
    assert result.final_sql
    ctx = UserContext(username="finance", role=RoleName.FINANCE_ANALYST)
    rows = await run_readonly(result.final_sql, ctx, 5000, 1000, engine=analytics_engine)
    assert rows.row_count == 8
    assert rows.columns == ["category_name", "revenue"]


async def test_expanded_star_runs_and_hides_columns(analytics_engine: AsyncEngine) -> None:
    result = validate("SELECT * FROM customers", RoleName.OPERATIONS_MANAGER, LAYER)
    assert result.final_sql
    ctx = UserContext(username="operations", role=RoleName.OPERATIONS_MANAGER)
    rows = await run_readonly(result.final_sql, ctx, 5000, 1000, engine=analytics_engine)
    assert "contact_name" not in rows.columns
    assert rows.row_count == 91


async def test_region_filter_still_applies_to_validated_sql(analytics_engine: AsyncEngine) -> None:
    result = validate("SELECT DISTINCT country FROM customers", RoleName.SALES_MANAGER, LAYER)
    assert result.final_sql
    ctx = UserContext(username="sales.other", role=RoleName.SALES_MANAGER, region=RegionCode.ROW)
    rows = await run_readonly(result.final_sql, ctx, 5000, 1000, engine=analytics_engine)
    assert {r[0] for r in rows.rows} == {"Brazil", "Argentina", "Venezuela"}


async def test_database_blocks_what_the_validator_would_block(
    analytics_engine: AsyncEngine,
) -> None:
    """Defence in depth: even unvalidated hidden-column SQL fails in the database."""
    ctx = UserContext(username="operations", role=RoleName.OPERATIONS_MANAGER)
    assert validate("SELECT contact_name FROM customers", ctx.role, LAYER).allowed is False
    with pytest.raises(ReadonlyQueryError):
        await run_readonly(
            "SELECT contact_name FROM customers", ctx, 5000, 10, engine=analytics_engine
        )
