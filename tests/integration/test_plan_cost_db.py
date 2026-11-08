"""Step 26 extra: EXPLAIN-based cost check refuses very expensive queries before they run."""

import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.deps import Executor
from app.agent.graph import Agent
from app.agent.state import AgentRequest
from app.core.config import PROJECT_ROOT, Settings
from app.core.context import UserContext
from app.core.enums import BlockReason, QuestionStatus, RegionCode, RoleName
from app.db.analytics import QueryResult, ReadonlyQueryError, run_readonly
from scripts.seed import SeedSummary
from tests.fakes import ScriptedModel, fake_deps, intent, sql_reply

pytestmark = pytest.mark.integration
CROSS_JOIN = "SELECT count(*) AS n FROM orders o, order_details od"
FINANCE = UserContext(username="t", role=RoleName.FINANCE_ANALYST, region=None)
EUROPE = UserContext(username="t", role=RoleName.SALES_MANAGER, region=RegionCode.EUROPE)


async def test_cross_join_is_refused_for_every_business_role(
    settings: Settings, seeded: SeedSummary, analytics_engine: AsyncEngine
) -> None:
    limit = settings.analytics.max_plan_cost
    assert limit > 0
    for user in (FINANCE, EUROPE):
        with pytest.raises(ReadonlyQueryError) as caught:
            await run_readonly(CROSS_JOIN, user, 5000, 10, engine=analytics_engine, max_cost=limit)
        assert caught.value.kind == "too_expensive"


async def test_every_verified_example_stays_under_the_limit(
    settings: Settings, seeded: SeedSummary, analytics_engine: AsyncEngine
) -> None:
    examples = yaml.safe_load(
        (PROJECT_ROOT / "config" / "verified_queries.yaml").read_text("utf-8")
    )
    roles = {"finance_analyst": FINANCE, "sales_manager": EUROPE}
    checked = 0
    for example in examples["examples"]:
        for role in example["allowed_roles"]:
            user = roles.get(role) or UserContext(username="t", role=RoleName(role), region=None)
            await run_readonly(
                example["sql"], user, 5000, 1000, engine=analytics_engine,
                max_cost=settings.analytics.max_plan_cost,
            )  # fmt: skip
            checked += 1
    assert checked >= 18


async def test_the_agent_blocks_and_records_an_expensive_query(
    settings: Settings, seeded: SeedSummary, analytics_engine: AsyncEngine
) -> None:
    async def execute(sql: str, user: UserContext, timeout_ms: int, row_limit: int) -> QueryResult:
        return await run_readonly(
            sql, user, timeout_ms, row_limit, engine=analytics_engine,
            max_cost=settings.analytics.max_plan_cost,
        )  # fmt: skip

    executor: Executor = execute
    model = ScriptedModel(
        intent(summary="Count pairs", metric=None, time_phrase=None),
        sql=[sql_reply(CROSS_JOIN, ["orders", "order_details"])],
    )
    deps = fake_deps(model, executor)
    request = AgentRequest(
        username="t", role=RoleName.FINANCE_ANALYST, region=None, is_active=True,
        question="Pair every order with every order line",
    )  # fmt: skip
    state = await Agent(deps).run(request)
    assert (state.status, state.block_reason) == (QuestionStatus.BLOCKED, BlockReason.TOO_EXPENSIVE)
    assert state.blocked is not None
    assert "estimated cost" in (state.blocked.detail or "")
    assert model.calls_by_kind["repair"] == []  # refused, not repaired
