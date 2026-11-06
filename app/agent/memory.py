"""PostgreSQL checkpointer for conversation state (brief section 18).

Runs as the application role with ``search_path`` set to the ``checkpoints`` schema; the
tables are created by the seed (``app/db/setup/checkpoints.py``), not at runtime.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

from app.agent.checkpoint import checkpoint_serializer
from app.core.config import Settings
from app.db.setup.checkpoints import CHECKPOINT_SCHEMA


def app_role_conninfo(settings: Settings) -> str:
    url = make_url(settings.app_database_url.get_secret_value()).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@asynccontextmanager
async def postgres_checkpointer(
    settings: Settings, *, max_size: int = 5
) -> AsyncIterator[AsyncPostgresSaver]:
    """A pooled AsyncPostgresSaver for the lifetime of the app (or a test)."""
    pool = AsyncConnectionPool(
        app_role_conninfo(settings),
        min_size=1,
        max_size=max_size,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": f"-c search_path={CHECKPOINT_SCHEMA}",
        },
    )
    await pool.open()
    try:
        yield AsyncPostgresSaver(pool, serde=checkpoint_serializer())  # type: ignore[arg-type]
    finally:
        await pool.close()
