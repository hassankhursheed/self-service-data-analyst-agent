"""Async engine and session factory for the application role (app schema only)."""

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def _skip_asyncpg_jit_toggle(engine: AsyncEngine) -> AsyncEngine:
    """Stop asyncpg from calling ``set_config('jit', ...)`` during type introspection.

    ``set_config`` is revoked from every role so a query cannot rewrite its own role or
    region (docs/access-control.md). asyncpg would otherwise call it before introspecting
    types such as ``uuid[]``. JIT is switched off for both login roles by the seed, so
    asyncpg's toggle is not needed.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:  # noqa: ANN401
        driver = getattr(dbapi_connection, "driver_connection", None)
        caps = getattr(driver, "_server_caps", None)
        if caps is not None and getattr(caps, "jit", False):
            driver._server_caps = caps._replace(jit=False)  # type: ignore[union-attr]

    return engine


def create_app_engine(settings: Settings) -> AsyncEngine:
    """Create the pooled async engine for ``APP_DATABASE_URL``. Does not connect yet."""
    pool = settings.database
    return _skip_asyncpg_jit_toggle(
        create_async_engine(
            settings.app_database_url.get_secret_value(),
            pool_size=pool.pool_size,
            max_overflow=pool.max_overflow,
            pool_timeout=pool.pool_timeout_seconds,
            pool_recycle=pool.pool_recycle_seconds,
            pool_pre_ping=True,
            connect_args={"timeout": pool.connect_timeout_seconds},
        )
    )


def create_analytics_engine(settings: Settings) -> AsyncEngine:
    """Pooled async engine for the read-only ``ANALYTICS_DATABASE_URL`` (agent queries)."""
    pool = settings.database
    return _skip_asyncpg_jit_toggle(
        create_async_engine(
            settings.analytics_database_url.get_secret_value(),
            pool_size=pool.pool_size,
            max_overflow=pool.max_overflow,
            pool_timeout=pool.pool_timeout_seconds,
            pool_recycle=pool.pool_recycle_seconds,
            pool_pre_ping=True,
            connect_args={"timeout": pool.connect_timeout_seconds},
        )
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory; objects stay usable after commit (no implicit reloads)."""
    return async_sessionmaker(engine, expire_on_commit=False)
