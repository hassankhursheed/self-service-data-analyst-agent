"""Shared fixtures for integration tests. They skip when PostgreSQL is not reachable
(and fail instead when REQUIRE_DATABASE=1, as in CI)."""

import os
from collections.abc import AsyncIterator, Iterator
from typing import NoReturn

import psycopg
import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.db.session import create_analytics_engine
from scripts.seed import SeedSummary, run_seed


def _skip_or_fail(reason: str) -> NoReturn:
    """Locally a missing database skips; in CI (REQUIRE_DATABASE=1) it fails, so the
    safety and access-control tests can never be skipped silently."""
    if os.environ.get("REQUIRE_DATABASE") == "1":
        pytest.fail(f"REQUIRE_DATABASE=1 but {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="session")
def settings() -> Settings:
    try:
        return get_settings()
    except ValidationError:
        _skip_or_fail("No database settings (.env missing); start Docker Compose first")


@pytest.fixture(scope="session")
def owner_conn(settings: Settings) -> Iterator[psycopg.Connection]:
    try:
        conn = psycopg.connect(settings.owner_conninfo(), connect_timeout=3, autocommit=True)
    except psycopg.OperationalError:
        _skip_or_fail("PostgreSQL is not reachable; run `docker compose up -d`")
    with conn:
        yield conn


@pytest.fixture(scope="session")
def seeded(owner_conn: psycopg.Connection, settings: Settings) -> SeedSummary:
    """Run the idempotent seed once per test session."""
    return run_seed(settings)


@pytest.fixture
def analytics_ro_conninfo(settings: Settings, seeded: SeedSummary) -> str:
    """libpq URL for logging in directly as the read-only analytics role."""
    url = make_url(settings.analytics_database_url.get_secret_value()).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@pytest.fixture
async def analytics_engine(settings: Settings, seeded: SeedSummary) -> AsyncIterator[AsyncEngine]:
    engine = create_analytics_engine(settings)
    yield engine
    await engine.dispose()
