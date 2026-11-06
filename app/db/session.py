"""Async engine and session factory for the application role (app schema only)."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_app_engine(settings: Settings) -> AsyncEngine:
    """Create the pooled async engine for ``APP_DATABASE_URL``. Does not connect yet."""
    pool = settings.database
    return create_async_engine(
        settings.app_database_url.get_secret_value(),
        pool_size=pool.pool_size,
        max_overflow=pool.max_overflow,
        pool_timeout=pool.pool_timeout_seconds,
        pool_recycle=pool.pool_recycle_seconds,
        pool_pre_ping=True,
        connect_args={"timeout": pool.connect_timeout_seconds},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory; objects stay usable after commit (no implicit reloads)."""
    return async_sessionmaker(engine, expire_on_commit=False)
