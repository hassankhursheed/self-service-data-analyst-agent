"""Checks the API runs before it accepts requests (Step 24)."""

import asyncio
import logging

import psycopg

from app.agent.deps import AgentDeps, app_conninfo
from app.core.config import Settings
from app.semantic.schema_check import SchemaDrift, check_semantic_catalog

logger = logging.getLogger(__name__)


async def check_schema(settings: Settings, deps: AgentDeps) -> None:
    """Fail start-up when the semantic layer does not match the database."""
    layer = await deps.load_semantic()

    def run() -> list[str]:
        with psycopg.connect(app_conninfo(settings), connect_timeout=5) as conn:
            return check_semantic_catalog(conn, layer)

    problems = await asyncio.to_thread(run)
    if problems:
        logger.error("schema drift: %s", "; ".join(problems))
        raise SchemaDrift(problems)
    logger.info("schema check passed: %d tables", len(layer.tables))
