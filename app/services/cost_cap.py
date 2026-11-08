"""Daily cost cap for a public demo (Step 25, docs/deployment.md).

Before a question runs, today's estimated LLM cost (UTC day, ``agent_runs``) is compared
with ``api.daily_cost_cap_usd``. When it is reached, new questions are refused with a
friendly message until the next day; the rest of the app keeps working. The sum is cached
for a few seconds so a burst of questions does not query it every time. A cap of 0 turns
the check off.
"""

import datetime as dt
import time
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.db.models import AgentRun


class DailyBudgetReached(AppError):
    code = "DAILY_BUDGET_REACHED"
    user_message = (
        "The demo has used today's question budget. Please try again tomorrow; "
        "everything else still works."
    )


class DailyCostCap:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cap_usd: float,
        *,
        cache_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.sessions = sessions
        self.cap = Decimal(str(cap_usd))
        self.cache_seconds = cache_seconds
        self.clock = clock
        self._cached: tuple[float, dt.date, Decimal] | None = None

    async def spent_today(self) -> Decimal:
        today = dt.datetime.now(dt.UTC).date()
        now = self.clock()
        if self._cached and self._cached[1] == today and now - self._cached[0] < self.cache_seconds:
            return self._cached[2]
        start = dt.datetime.combine(today, dt.time.min, tzinfo=dt.UTC)
        async with self.sessions() as session:
            spent = await session.scalar(
                select(func.coalesce(func.sum(AgentRun.estimated_cost_usd), 0)).where(
                    AgentRun.started_at >= start
                )
            )
        value = Decimal(spent or 0)
        self._cached = (now, today, value)
        return value

    async def check(self) -> None:
        """Raise DailyBudgetReached when today's spend has reached the cap."""
        if self.cap <= 0:
            return
        spent = await self.spent_today()
        if spent >= self.cap:
            raise DailyBudgetReached(f"spent {spent} of {self.cap} USD today")
