"""Database roles, grants and secure views (docs/access-control.md).

Idempotent: every run re-applies roles, grants and rebuilds the view schemas from
config/access_policy.yaml.
"""

import psycopg
from psycopg import sql
from pydantic import BaseModel
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.enums import RoleName
from app.db.models import APP_SCHEMA
from app.db.setup.northwind_data import SeedError
from app.safety.access_policy import REGION_LOOKUPS, AccessPolicy

ROLE_SETTING = "app.user_role"
REGION_SETTING = "app.user_region"


class LoginRole(BaseModel):
    name: str
    password: str


def login_role_from_url(url: str) -> LoginRole:
    parsed = make_url(url)
    if not parsed.username or not parsed.password:
        raise SeedError("database URLs must include a user name and password")
    return LoginRole(name=parsed.username, password=parsed.password)


def _ensure_login_role(conn: psycopg.Connection, role: LoginRole) -> None:
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role.name,)).fetchone()
    if exists is None:
        conn.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role.name)))
    conn.execute(
        sql.SQL(
            "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
            "NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(sql.Identifier(role.name), sql.Literal(role.password))
    )


def _base_columns(conn: psycopg.Connection, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    if not rows:
        raise SeedError(f"Northwind table public.{table} not found")
    return [str(r[0]) for r in rows]


def view_definition(
    policy: AccessPolicy, role_name: str, table: str, columns: list[str]
) -> sql.Composed:
    """SELECT for one secure view: allowed columns, role check, and region filter."""
    role = RoleName(role_name)
    rule = policy.roles[role]
    visible = policy.visible_columns(role, table, columns)
    if not visible:
        raise SeedError(f"{role}: no visible columns in {table}")
    conditions: list[sql.Composable] = [
        sql.SQL("current_setting({}, true) = {}").format(
            sql.Literal(ROLE_SETTING), sql.Literal(role.value)
        )
    ]
    key = policy.region_keys.get(table)
    if rule.region_scoped and key is not None:
        conditions.append(
            sql.SQL(
                "t.{key} IN (SELECT {key} FROM analytics.{lookup} "
                "WHERE region_code = current_setting({setting}, true))"
            ).format(
                key=sql.Identifier(key),
                lookup=sql.Identifier(REGION_LOOKUPS[key]),
                setting=sql.Literal(REGION_SETTING),
            )
        )
    return sql.SQL("SELECT {cols} FROM public.{table} AS t WHERE {where}").format(
        cols=sql.SQL(", ").join(sql.SQL("t.{}").format(sql.Identifier(c)) for c in visible),
        table=sql.Identifier(table),
        where=sql.SQL(" AND ").join(conditions),
    )


def setup_database_access(
    conn: psycopg.Connection, settings: Settings, policy: AccessPolicy
) -> dict[str, int]:
    """Create login roles, lock down privileges and rebuild the secure views.

    Returns the number of views per view schema.
    """
    app_role = login_role_from_url(settings.app_database_url.get_secret_value())
    ro_role = login_role_from_url(settings.analytics_database_url.get_secret_value())
    owner = sql.Identifier(settings.postgres_user)
    app_id, ro_id = sql.Identifier(app_role.name), sql.Identifier(ro_role.name)
    db = sql.Identifier(settings.postgres_db)
    views: dict[str, int] = {}

    with conn.transaction():
        _ensure_login_role(conn, app_role)
        _ensure_login_role(conn, ro_role)

        # Nobody gets anything by default: no CONNECT, no TEMP, no public-schema access.
        for stmt in (
            "REVOKE ALL ON DATABASE {db} FROM PUBLIC",
            "GRANT CONNECT ON DATABASE {db} TO {app}, {ro}",
            "REVOKE ALL ON SCHEMA public FROM PUBLIC",
            "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC",
            "REVOKE ALL ON SCHEMA analytics FROM PUBLIC",
            "REVOKE ALL ON ALL TABLES IN SCHEMA analytics FROM PUBLIC",
            # set_config() could rewrite the session's role or region inside a SELECT.
            "REVOKE EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) FROM PUBLIC",
            # Application role: read and write application data only.
            "REVOKE ALL ON SCHEMA {app_schema} FROM PUBLIC",
            "GRANT USAGE ON SCHEMA {app_schema} TO {app}",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {app_schema} TO {app}",
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {app_schema} TO {app}",
            "ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA {app_schema} "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app}",
            "ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA {app_schema} "
            "GRANT USAGE, SELECT ON SEQUENCES TO {app}",
            "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {app_schema}.alembic_version FROM {app}",
            # Conversation state (LangGraph checkpointer tables, created by the seed).
            "REVOKE ALL ON SCHEMA checkpoints FROM PUBLIC",
            "GRANT USAGE ON SCHEMA checkpoints TO {app}",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA checkpoints TO {app}",
            "ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA checkpoints "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app}",
            # Analytics role: read-only by default, with a backstop timeout.
            "ALTER ROLE {ro} SET default_transaction_read_only = on",
            "ALTER ROLE {ro} SET statement_timeout = {timeout}",
        ):
            conn.execute(
                sql.SQL(stmt).format(
                    db=db,
                    app=app_id,
                    ro=ro_id,
                    owner=owner,
                    app_schema=sql.Identifier(APP_SCHEMA),
                    timeout=sql.Literal(str(settings.analytics.role_statement_timeout_ms)),
                )
            )

        # One schema of secure views per business role, rebuilt from the policy.
        for role_name, rule in policy.roles.items():
            if rule.view_schema is None:
                continue
            schema = sql.Identifier(rule.view_schema)
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(schema))
            conn.execute(sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(schema, owner))
            conn.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(schema))
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, ro_id))
            for table in rule.tables:
                body = view_definition(policy, role_name.value, table, _base_columns(conn, table))
                conn.execute(
                    sql.SQL("CREATE VIEW {}.{} WITH (security_barrier = true) AS {}").format(
                        schema, sql.Identifier(table), body
                    )
                )
            conn.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(schema, ro_id)
            )
            views[rule.view_schema] = len(rule.tables)
    return views
