"""Small synchronous connection pools for per-question lookups (Step 24).

The semantic layer and the verified library are read for every question with psycopg in a
worker thread (``asyncio.to_thread``). They reuse connections from one pool per loader
instead of opening a new connection each time.

The pool opens on first use, exactly once: many questions arriving together run their
lookups in parallel threads, and opening one psycopg pool from several threads at once
makes them wait for the open timeout or fail (found by the Step 26 load test).
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool


class LookupPool:
    """A lazily opened, thread-safe connection pool."""

    def __init__(self, conninfo: str, *, max_size: int = 4) -> None:
        self.pool = ConnectionPool(
            conninfo,
            min_size=1,
            max_size=max_size,
            open=False,
            check=ConnectionPool.check_connection,
            kwargs={"connect_timeout": 5},
            name="lookup",
        )
        self._lock = threading.Lock()
        self._opened = False

    def _ensure_open(self) -> None:
        if self._opened:
            return
        with self._lock:
            if not self._opened:
                self.pool.open(wait=True)
                self._opened = True

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        self._ensure_open()
        with self.pool.connection() as conn:
            yield conn

    def close(self) -> None:
        with self._lock:
            if self._opened:
                self.pool.close()
                self._opened = False


def lookup_pool(conninfo: str, *, max_size: int = 4) -> LookupPool:
    """A pool that opens on first use; connections are checked before reuse."""
    return LookupPool(conninfo, max_size=max_size)
