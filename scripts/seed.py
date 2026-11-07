"""Idempotent seed: prepares the database, Northwind data, access rules and test users.

Usage: python -m scripts.seed

Steps (each safe to run again):
1. wait until PostgreSQL accepts connections;
2. run Alembic migrations (app schema);
3. shift Northwind dates once (recorded in analytics.data_setup);
4. sync the sales-region mapping;
5. sync roles and the test users from config/test_users.yaml;
6. create database login roles, grants and the secure views (docs/access-control.md);
7. sync the semantic layer into the catalog tables and check it against the database;
8. sync the business calendar (config/calendar.yaml);
9. create the LangGraph checkpoint tables in schema ``checkpoints`` (before the grants);
10. add the seeded verified examples (config/verified_queries.yaml) that are not there yet.
"""

import sys
import time

import psycopg
from alembic import command
from alembic.config import Config
from pydantic import BaseModel

from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.core.yaml_config import ConfigFileError
from app.db.setup.access import setup_database_access
from app.db.setup.checkpoints import setup_checkpoint_tables
from app.db.setup.northwind_data import (
    SeedError,
    apply_date_shift,
    ensure_analytics_schema,
    load_regions,
    sync_regions,
)
from app.db.setup.users import load_test_users, sync_roles, sync_test_users
from app.safety.access_policy import load_access_policy
from app.semantic.calendar import load_calendar
from app.semantic.calendar_store import sync_calendar
from app.semantic.catalog import load_semantic_layer_file, sync_semantic_layer
from app.semantic.schema_check import check_semantic_schema
from app.semantic.verified import load_seed_file, sync_seed_examples


class SeedSummary(BaseModel):
    date_shift_years: int
    date_shift_applied_now: bool
    customers_per_region: dict[str, int]
    roles: int
    test_users: int
    view_schemas: dict[str, int]
    semantic_version: int
    semantic_catalog_rows: int
    metrics: int
    calendar_version: int
    reference_date: str
    verified_examples_added: int


def wait_for_database(settings: Settings) -> None:
    deadline = time.monotonic() + settings.data_setup.wait_for_db_seconds
    while True:
        try:
            with psycopg.connect(settings.owner_conninfo(), connect_timeout=3):
                return
        except psycopg.OperationalError as exc:
            if time.monotonic() > deadline:
                raise SeedError(f"database not reachable: {exc}") from exc
            time.sleep(1)


def run_migrations() -> None:
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")


def run_seed(settings: Settings | None = None) -> SeedSummary:
    settings = settings or get_settings()
    policy = load_access_policy()
    regions = load_regions()
    users = load_test_users()
    layer = load_semantic_layer_file()
    calendar = load_calendar()
    verified = load_seed_file()

    wait_for_database(settings)
    run_migrations()
    setup_checkpoint_tables(settings)
    with psycopg.connect(settings.owner_conninfo(), autocommit=True) as conn:
        ensure_analytics_schema(conn)
        shifted_now = apply_date_shift(conn, settings.data_setup.date_shift_years)
        per_region = sync_regions(conn, regions)
        role_ids = sync_roles(conn, policy)
        user_count = sync_test_users(conn, users, role_ids, settings)
        views = setup_database_access(conn, settings, policy)
        problems = check_semantic_schema(conn, layer)
        if problems:
            raise SeedError("semantic layer does not match the database: " + "; ".join(problems))
        semantic = sync_semantic_layer(conn, layer)
        calendar_version = sync_calendar(conn, calendar)
        try:
            verified_added = sync_seed_examples(conn, verified, layer)
        except ValueError as exc:
            raise SeedError(str(exc)) from exc
    return SeedSummary(
        date_shift_years=settings.data_setup.date_shift_years,
        date_shift_applied_now=shifted_now,
        customers_per_region=per_region,
        roles=len(role_ids),
        test_users=user_count,
        view_schemas=views,
        semantic_version=semantic["version"],
        semantic_catalog_rows=semantic["catalog_rows"],
        metrics=semantic["metrics"],
        calendar_version=calendar_version,
        reference_date=calendar.reference_date.isoformat(),
        verified_examples_added=verified_added,
    )


def main() -> int:
    try:
        summary = run_seed()
    except (SeedError, ConfigFileError) as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        return 1
    shift = "applied now" if summary.date_shift_applied_now else "already applied"
    print("Seed complete")
    print(f"  date shift:      +{summary.date_shift_years} years ({shift})")
    print(f"  customers/region: {summary.customers_per_region}")
    print(f"  roles:           {summary.roles}")
    print(f"  test users:      {summary.test_users}")
    print(f"  secure views:    {summary.view_schemas}")
    print(
        f"  semantic layer:  v{summary.semantic_version}, "
        f"{summary.semantic_catalog_rows} catalog rows, {summary.metrics} metrics"
    )
    print(
        f"  calendar:        v{summary.calendar_version}, business today {summary.reference_date}"
    )
    print(f"  verified queries: {summary.verified_examples_added} seeded examples added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
