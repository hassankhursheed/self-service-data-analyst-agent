"""Shared fixtures for integration tests. They skip when PostgreSQL is not reachable."""

from collections.abc import Iterator

import psycopg
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    try:
        return get_settings()
    except ValidationError:
        pytest.skip("No database settings (.env missing); start Docker Compose first")


@pytest.fixture(scope="session")
def owner_conn(settings: Settings) -> Iterator[psycopg.Connection]:
    try:
        conn = psycopg.connect(settings.owner_conninfo(), connect_timeout=3, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL is not reachable; run `docker compose up -d`")
    with conn:
        yield conn
