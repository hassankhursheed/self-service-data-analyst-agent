"""Run agent SQL as the read-only analytics role, scoped to one user's role and region.

Every query runs in its own READ ONLY transaction that sets, with SET LOCAL:
- ``search_path`` to the role's secure-view schema (sales_ro, finance_ro, operations_ro),
- ``app.user_role`` and ``app.user_region`` (read by the views; missing values return no
  rows),
- ``statement_timeout``.

With ``max_cost`` the plan is checked first (``EXPLAIN``, which does not run the query)
and a query whose estimated total cost is higher is refused with kind ``too_expensive``.

The query itself is sent as a prepared statement, so only one statement can run, and
``set_config`` is not executable by the role, so a query cannot change its own scope.
"""

import asyncio
import json
from functools import lru_cache
from typing import Any

import asyncpg
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.context import UserContext
from app.db.session import create_analytics_engine
from app.db.setup.access import REGION_SETTING, ROLE_SETTING
from app.safety.access_policy import AccessPolicy, get_access_policy


class QueryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    columns: list[str]
    rows: list[tuple[Any, ...]]
    row_count: int
    truncated: bool


class ReadonlyQueryError(Exception):
    """The query was refused or failed. ``kind`` is a stable code for the caller."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@lru_cache
def _default_engine() -> AsyncEngine:
    return create_analytics_engine(get_settings())


def session_statements(user_ctx: UserContext, timeout_ms: int, policy: AccessPolicy) -> list[str]:
    """SET LOCAL statements for one transaction. Values come only from validated enums."""
    schema = policy.roles[user_ctx.role].view_schema
    if schema is None:
        raise ReadonlyQueryError("no_data_access", f"role {user_ctx.role} has no business data")
    if not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ReadonlyQueryError("invalid_limit", "timeout_ms must be a positive integer")
    statements = [
        f"SET LOCAL statement_timeout = {timeout_ms}",
        f'SET LOCAL search_path = "{schema}"',
        f"SET LOCAL {ROLE_SETTING} = '{user_ctx.role.value}'",
    ]
    if user_ctx.region is not None:
        statements.append(f"SET LOCAL {REGION_SETTING} = '{user_ctx.region.value}'")
    return statements


def plan_cost(explain_json: object) -> float:
    """Estimated total cost from ``EXPLAIN (FORMAT JSON)`` output."""
    data = json.loads(explain_json) if isinstance(explain_json, str) else explain_json
    if not isinstance(data, list) or not data or "Plan" not in data[0]:
        raise ReadonlyQueryError("db_error", "unexpected EXPLAIN output")
    return float(data[0]["Plan"]["Total Cost"])


async def _check_plan_cost(conn: asyncpg.Connection, sql: str, max_cost: float) -> None:
    # ``sql`` already passed the validator (one SELECT); EXPLAIN without ANALYZE only plans.
    cost = plan_cost(await conn.fetchval("EXPLAIN (FORMAT JSON) " + sql))
    if cost > max_cost:
        raise ReadonlyQueryError(
            "too_expensive", f"estimated cost {cost:.0f} is above the limit {max_cost:.0f}"
        )


async def run_readonly(
    sql: str,
    user_ctx: UserContext,
    timeout_ms: int,
    row_limit: int,
    *,
    engine: AsyncEngine | None = None,
    policy: AccessPolicy | None = None,
    max_cost: float = 0.0,
) -> QueryResult:
    """Execute one SELECT for ``user_ctx`` and return at most ``row_limit`` rows."""
    if row_limit <= 0:
        raise ReadonlyQueryError("invalid_limit", "row_limit must be positive")
    statements = session_statements(user_ctx, timeout_ms, policy or get_access_policy())
    engine = engine or _default_engine()
    try:
        async with engine.connect() as sa_conn:
            raw = await sa_conn.get_raw_connection()
            conn: Any = raw.driver_connection
            async with conn.transaction(readonly=True):
                for statement in statements:
                    await conn.execute(statement)
                async with asyncio.timeout(timeout_ms / 1000 + 5):
                    if max_cost > 0:
                        await _check_plan_cost(conn, sql, max_cost)
                    prepared = await conn.prepare(sql)
                    columns = [attr.name for attr in prepared.get_attributes()]
                    cursor = await prepared.cursor()
                    records = await cursor.fetch(row_limit + 1)
    except asyncpg.exceptions.QueryCanceledError as exc:
        raise ReadonlyQueryError("timeout", "the query took too long and was stopped") from exc
    except TimeoutError as exc:
        raise ReadonlyQueryError("timeout", "the query took too long and was stopped") from exc
    except asyncpg.exceptions.InsufficientPrivilegeError as exc:
        raise ReadonlyQueryError("permission_denied", str(exc)) from exc
    except asyncpg.exceptions.ReadOnlySQLTransactionError as exc:
        raise ReadonlyQueryError("read_only", str(exc)) from exc
    except asyncpg.exceptions.PostgresError as exc:
        raise ReadonlyQueryError("db_error", str(exc)) from exc
    truncated = len(records) > row_limit
    rows = [tuple(record.values()) for record in records[:row_limit]]
    return QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)
