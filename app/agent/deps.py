"""Everything the nodes need from outside the state, passed in once when the graph is built.

Tests build ``AgentDeps`` with a scripted LLM, a fake executor and a fixed semantic layer;
the app uses ``default_deps()``.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from langchain_core.messages import BaseMessage
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.audit import AuditSink, DatabaseAuditSink, MemoryAuditSink
from app.agent.config import AgentConfig, get_agent_config
from app.agent.state import AgentState, Usage
from app.agent.tracing import redacting_client
from app.core.config import Settings, get_settings
from app.core.context import UserContext
from app.core.enums import RoleName
from app.core.llm import BudgetTracker, LLMClient, LLMConfig, create_llm_client, get_llm_config
from app.core.prompts import load_prompt
from app.db.analytics import QueryResult, run_readonly
from app.db.pools import lookup_pool
from app.db.session import create_analytics_engine, create_app_engine, create_session_factory
from app.safety.access_policy import get_access_policy
from app.safety.sql_policy import SqlPolicy, get_sql_policy
from app.semantic.calendar import CalendarConfig, load_calendar
from app.semantic.catalog import load_active_semantic_layer
from app.semantic.models import SemanticLayer
from app.semantic.verified import VerifiedExample, VerifiedLoader, database_verified_loader

# (sql, user, timeout_ms, row_limit) -> rows. The default runs through analytics_ro.
Executor = Callable[[str, UserContext, int, int], Awaitable[QueryResult]]
SemanticLoader = Callable[[], Awaitable[SemanticLayer]]
Sleep = Callable[[float], Awaitable[None]]


async def no_verified_examples() -> list[VerifiedExample]:
    """Default loader (unit tests): an empty library."""
    return []


@dataclass(frozen=True)
class AgentDeps:
    llm: LLMClient
    llm_config: LLMConfig
    agent_config: AgentConfig
    calendar: CalendarConfig
    load_semantic: SemanticLoader
    executor: Executor
    sql_policy: SqlPolicy
    statement_timeout_ms: int
    row_limit: int
    audit: AuditSink = field(default_factory=MemoryAuditSink)
    load_verified: VerifiedLoader = field(default=no_verified_examples)
    # LangSmith client that redacts traces (None: tracing off or env defaults).
    trace_client: Any = None
    sleep: Sleep = field(default=asyncio.sleep)

    def budget_for(self, state: AgentState) -> BudgetTracker:
        """The question's budget, continuing from what earlier nodes already spent."""
        return BudgetTracker(
            self.llm_config.budget,
            self.llm_config.pricing,
            spent_input_tokens=state.usage.input_tokens,
            spent_output_tokens=state.usage.output_tokens,
            spent_cost_usd=state.usage.cost_usd,
        )

    def view_schema(self, role: RoleName) -> str | None:
        """The secure-view schema the role's queries run against (recorded in the audit)."""
        return get_access_policy().roles[role].view_schema

    def system_messages(self) -> list[BaseMessage]:
        prompt = load_prompt("system", self.llm_config.prompts["system"])
        return list(
            prompt.to_chat_prompt().format_messages(
                business_today=self.calendar.reference_date.isoformat()
            )
        )


def usage_of(budget: BudgetTracker) -> Usage:
    return Usage(
        input_tokens=budget.input_tokens,
        output_tokens=budget.output_tokens,
        cost_usd=budget.cost_usd,
    )


def app_conninfo(settings: Settings) -> str:
    url = make_url(settings.app_database_url.get_secret_value()).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def database_semantic_loader(settings: Settings) -> SemanticLoader:
    """Read the active semantic layer from the database for every question (app role)."""
    pool = lookup_pool(app_conninfo(settings))

    def load() -> SemanticLayer:
        with pool.connection() as conn:
            return load_active_semantic_layer(conn)

    async def load_async() -> SemanticLayer:
        return await asyncio.to_thread(load)

    return load_async


def analytics_executor(settings: Settings) -> Executor:
    """Run validated SQL through the read-only analytics role (one pooled engine)."""

    @lru_cache
    def engine() -> AsyncEngine:
        return create_analytics_engine(settings)

    async def execute(sql: str, user: UserContext, timeout_ms: int, row_limit: int) -> QueryResult:
        return await run_readonly(
            sql,
            user,
            timeout_ms,
            row_limit,
            engine=engine(),
            max_cost=settings.analytics.max_plan_cost,
        )

    return execute


def default_deps() -> AgentDeps:
    """Production wiring: real LLM, database semantic layer and read-only executor."""
    settings = get_settings()
    llm_config = get_llm_config()
    return AgentDeps(
        audit=DatabaseAuditSink(
            create_session_factory(create_app_engine(settings)),
            model_name=llm_config.model,
            trace_project=settings.langsmith_project,
        ),
        llm=create_llm_client(settings),
        llm_config=get_llm_config(),
        agent_config=get_agent_config(),
        calendar=load_calendar(),
        load_semantic=database_semantic_loader(settings),
        load_verified=database_verified_loader(app_conninfo(settings)),
        trace_client=redacting_client(settings),
        executor=analytics_executor(settings),
        sql_policy=get_sql_policy(),
        statement_timeout_ms=settings.analytics.default_statement_timeout_ms,
        row_limit=settings.analytics.default_row_limit,
    )
