"""Create the LangGraph checkpoint tables in their own schema (run by the seed as owner)."""

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

from app.core.config import Settings

CHECKPOINT_SCHEMA = "checkpoints"


def setup_checkpoint_tables(settings: Settings) -> None:
    """Idempotent: creates schema ``checkpoints`` and runs the checkpointer migrations."""
    with psycopg.connect(settings.owner_conninfo(), autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{CHECKPOINT_SCHEMA}"')
    conninfo = settings.owner_conninfo() + f" options='-c search_path={CHECKPOINT_SCHEMA}'"
    with psycopg.connect(conninfo, autocommit=True, row_factory=dict_row) as conn:
        PostgresSaver(conn).setup()
