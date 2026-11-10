"""Unit tests for Steps 5-6 config, password hashing, user context and secure-view SQL."""

import pytest
from psycopg import sql
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.context import UserContext
from app.core.enums import RegionCode, RoleName
from app.core.security import hash_password, verify_password
from app.db.analytics import ReadonlyQueryError, session_statements
from app.db.setup.access import login_role_from_url, view_definition
from app.db.setup.northwind_data import RegionsConfig, load_regions
from app.db.setup.users import load_test_users
from app.safety.access_policy import load_access_policy

POLICY = load_access_policy()


def test_password_hashing_uses_argon2_and_verifies() -> None:
    hashed = hash_password("demo-secret")
    assert hashed.startswith("$argon2")
    assert verify_password(hashed, "demo-secret")
    assert not verify_password(hashed, "wrong")
    assert not verify_password("not-a-hash", "demo-secret")


def test_regions_cover_every_code_once() -> None:
    regions = load_regions()
    assert {r.code for r in regions.regions} == set(RegionCode)
    with pytest.raises(ValidationError, match="more than one region"):
        RegionsConfig.model_validate(
            {
                "version": 1,
                "regions": [
                    {"code": "EUROPE", "name": "E", "countries": ["UK"]},
                    {"code": "AMERICAS", "name": "A", "countries": ["UK"]},
                    {"code": "ROW", "name": "R", "countries": []},
                ],
            }
        )


def test_test_users_match_brief_section_7() -> None:
    users = {u.username: u for u in load_test_users().users}
    assert set(users) == {
        "sales.europe", "sales.americas", "sales.other", "finance",
        "operations", "admin", "no.role", "disabled.user",
    }  # fmt: skip
    assert users["no.role"].role is None
    assert users["disabled.user"].is_active is False


def test_demo_password_maps_username_to_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Independent of the environment (CI sets every DEMO_PASSWORD_* variable).
    monkeypatch.delenv("DEMO_PASSWORD_SALES_EUROPE", raising=False)
    settings = Settings(
        _env_file=None,
        app_database_url=SecretStr("postgresql+asyncpg://a:b@h/d"),
        analytics_database_url=SecretStr("postgresql+asyncpg://a:b@h/d"),
        jwt_secret_key=SecretStr("x"),
        postgres_user="o",
        postgres_password=SecretStr("p"),
        demo_password_no_role=SecretStr("pw"),
    )
    secret = settings.demo_password("no.role")
    assert secret is not None
    assert secret.get_secret_value() == "pw"
    assert settings.demo_password("sales.europe") is None


def test_sensitive_columns_are_hidden_by_role() -> None:
    employee_cols = ["employee_id", "first_name", "address", "home_phone", "birth_date", "notes"]
    for role in POLICY.business_roles():
        assert POLICY.visible_columns(role, "employees", employee_cols) == [
            "employee_id",
            "first_name",
        ]
    assert POLICY.is_column_visible(RoleName.SALES_MANAGER, "customers", "contact_name")
    assert not POLICY.is_column_visible(RoleName.OPERATIONS_MANAGER, "customers", "contact_name")
    assert not POLICY.is_column_visible(RoleName.FINANCE_ANALYST, "customers", "phone")
    assert POLICY.is_column_visible(RoleName.OPERATIONS_MANAGER, "suppliers", "contact_name")
    assert POLICY.tables_for(RoleName.ADMIN) == []


def test_sales_view_filters_by_role_and_region() -> None:
    body = view_definition(POLICY, "sales_manager", "orders", ["order_id", "customer_id"])
    text = body.as_string(None)
    assert "current_setting('app.user_role', true) = 'sales_manager'" in text
    assert 'analytics"."order_regions"' in text or 'analytics."order_regions"' in text
    assert "current_setting('app.user_region', true)" in text


def test_finance_view_has_no_region_filter_and_hides_columns() -> None:
    body = view_definition(POLICY, "finance_analyst", "employees", ["employee_id", "birth_date"])
    text = body.as_string(None)
    assert "app.user_region" not in text
    assert "birth_date" not in text
    assert isinstance(body, sql.Composed)


def test_login_role_is_read_from_the_database_url() -> None:
    role = login_role_from_url("postgresql+asyncpg://analytics_ro:s3cret@localhost:5433/northwind")
    assert (role.name, role.password) == ("analytics_ro", "s3cret")


def test_user_context_requires_region_only_for_sales() -> None:
    with pytest.raises(ValidationError):
        UserContext(username="x", role=RoleName.SALES_MANAGER)
    with pytest.raises(ValidationError):
        UserContext(username="x", role=RoleName.FINANCE_ANALYST, region=RegionCode.EUROPE)


def test_session_statements_come_from_enums_only() -> None:
    ctx = UserContext(username="s", role=RoleName.SALES_MANAGER, region=RegionCode.ROW)
    statements = session_statements(ctx, 1500, POLICY)
    assert statements == [
        "SET LOCAL statement_timeout = 1500",
        'SET LOCAL search_path = "sales_ro"',
        "SET LOCAL app.user_role = 'sales_manager'",
        "SET LOCAL app.user_region = 'ROW'",
    ]
    with pytest.raises(ReadonlyQueryError):
        session_statements(UserContext(username="a", role=RoleName.ADMIN), 1500, POLICY)


def test_seed_refreshes_statistics_for_every_northwind_and_region_table() -> None:
    """Plan costs must not depend on whether autovacuum has run yet (flaky CI cost check)."""
    from app.db.northwind import NORTHWIND_TABLES
    from app.db.setup.northwind_data import refresh_statistics

    class Conn:
        def __init__(self) -> None:
            self.sql: list[str] = []

        def execute(self, sql: str) -> None:
            self.sql.append(sql)

    conn = Conn()
    tables = refresh_statistics(conn)  # type: ignore[arg-type]
    assert conn.sql == [f"ANALYZE {t}" for t in tables]
    assert {f"public.{t}" for t in NORTHWIND_TABLES} <= set(tables)
    assert "analytics.country_region" in tables
