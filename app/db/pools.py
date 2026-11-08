"""Small synchronous connection pools for per-question lookups (Step 24).

The semantic layer and the verified library are read for every question with psycopg in a
worker thread (``asyncio.to_thread``). They reuse connections from one pool per loader
instead of opening a new connection each time.
"""

from psycopg_pool import ConnectionPool


def lookup_pool(conninfo: str, *, max_size: int = 4) -> ConnectionPool:
    """A pool that opens on first use; connections are checked before reuse."""
    return ConnectionPool(
        conninfo,
        min_size=1,
        max_size=max_size,
        open=False,
        check=ConnectionPool.check_connection,
        kwargs={"connect_timeout": 5},
        name="lookup",
    )
