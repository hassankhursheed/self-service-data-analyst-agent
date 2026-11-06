"""Step 5: the seed is idempotent, shifts dates once, maps regions and creates test users."""

import datetime as dt

import psycopg
import pytest

from app.core.config import Settings
from scripts.seed import SeedSummary, run_seed

pytestmark = pytest.mark.integration

COUNTED = [
    "app.users",
    "app.roles",
    "app.user_roles",
    "app.user_regions",
    "app.semantic_catalog",
    "app.metric_definitions",
    "analytics.country_region",
    "analytics.sales_regions",
    "analytics.data_setup",
    "public.orders",
    "public.customers",
]


def _counts(conn: psycopg.Connection) -> dict[str, int]:
    counts = {}
    for table in COUNTED:
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608 (fixed names)
        counts[table] = int(row[0]) if row else -1
    return counts


def _order_date_range(conn: psycopg.Connection) -> tuple[dt.date, dt.date]:
    row = conn.execute("SELECT min(order_date), max(order_date) FROM public.orders").fetchone()
    assert row is not None
    return row[0], row[1]


def test_running_the_seed_twice_changes_nothing(
    seeded: SeedSummary, owner_conn: psycopg.Connection, settings: Settings
) -> None:
    before_counts, before_dates = _counts(owner_conn), _order_date_range(owner_conn)
    second = run_seed(settings)
    assert second.date_shift_applied_now is False
    assert _counts(owner_conn) == before_counts
    assert _order_date_range(owner_conn) == before_dates


def test_dates_are_shifted_exactly_27_years(
    seeded: SeedSummary, owner_conn: psycopg.Connection
) -> None:
    assert _order_date_range(owner_conn) == (dt.date(2023, 7, 4), dt.date(2025, 5, 6))
    row = owner_conn.execute(
        "SELECT count(*), max(value) FROM analytics.data_setup WHERE key = 'date_shift_years'"
    ).fetchone()
    assert row == (1, "27")


def test_every_customer_and_order_has_exactly_one_region(
    seeded: SeedSummary, owner_conn: psycopg.Connection
) -> None:
    customers = owner_conn.execute(
        "SELECT c.customer_id, count(cr.region_code) FROM public.customers c "
        "LEFT JOIN analytics.customer_regions cr USING (customer_id) GROUP BY 1"
    ).fetchall()
    assert len(customers) == 91
    assert all(n == 1 for _, n in customers)
    orders = owner_conn.execute(
        "SELECT o.order_id, count(r.region_code) FROM public.orders o "
        "LEFT JOIN analytics.order_regions r USING (order_id) GROUP BY 1"
    ).fetchall()
    assert len(orders) == 830
    assert all(n == 1 for _, n in orders)
    assert seeded.customers_per_region == {"EUROPE": 54, "AMERICAS": 21, "ROW": 16}


EXPECTED_USERS = {
    "sales.europe": ("sales_manager", ["EUROPE"], True),
    "sales.americas": ("sales_manager", ["AMERICAS"], True),
    "sales.other": ("sales_manager", ["ROW"], True),
    "finance": ("finance_analyst", [], True),
    "operations": ("operations_manager", [], True),
    "admin": ("admin", [], True),
    "no.role": (None, [], True),
    "disabled.user": ("finance_analyst", [], False),
}


def test_all_eight_test_users_have_the_right_role_region_and_flag(
    seeded: SeedSummary, owner_conn: psycopg.Connection
) -> None:
    rows = owner_conn.execute(
        "SELECT u.username, r.name, "
        "  coalesce(array_agg(ur.region_code) FILTER (WHERE ur.region_code IS NOT NULL), '{}'), "
        "  u.is_active, u.password_hash "
        "FROM app.users u "
        "LEFT JOIN app.user_roles uro ON uro.user_id = u.id "
        "LEFT JOIN app.roles r ON r.id = uro.role_id "
        "LEFT JOIN app.user_regions ur ON ur.user_id = u.id "
        "WHERE u.username = ANY(%s) GROUP BY u.username, r.name, u.is_active, u.password_hash",
        (list(EXPECTED_USERS),),
    ).fetchall()
    actual = {name: (role, list(regions), active) for name, role, regions, active, _ in rows}
    assert actual == EXPECTED_USERS
    assert all(str(h).startswith("$argon2") for *_, h in rows)
