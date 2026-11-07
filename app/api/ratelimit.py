"""In-memory sliding-window rate limiter (one API process; see docs/api.md)."""

import time
from collections import defaultdict, deque
from collections.abc import Callable

from app.api.errors import RateLimited


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Count one request for ``key``; raise RateLimited when over the limit."""
        now = self.clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            raise RateLimited(f"rate limit for {key}")
        hits.append(now)
