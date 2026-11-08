"""FastAPI application factory (brief §19). Run with ``python scripts/run_api.py``.

The lifespan opens the database engine, the PostgreSQL checkpointer and the agent once,
and closes them on shutdown. Tests pass their own agent dependencies and checkpointer.
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.conversations import ConversationService
from app.agent.deps import AgentDeps, default_deps
from app.agent.graph import Agent
from app.agent.memory import postgres_checkpointer
from app.api.deps import Services
from app.api.errors import install_error_handlers
from app.api.middleware import HEADER, CorrelationIdMiddleware
from app.api.ratelimit import SlidingWindowLimiter
from app.api.routes import admin, public, questions
from app.api.startup import check_schema
from app.auth.service import AuthService
from app.auth.tokens import TokenService
from app.core.config import Settings, get_settings
from app.core.log_masking import install_log_masking
from app.db.session import create_app_engine, create_session_factory
from app.eval.runner import EvalRunner, pinned_llm_factory, require_llm_key
from app.services.cost_cap import DailyCostCap
from app.services.evaluation import EvaluationService
from app.services.feedback import FeedbackService
from app.services.metrics import MetricsService
from app.services.review import ReviewService
from app.services.users import UserAdminService
from app.services.verified_library import VerifiedLibraryService


def create_app(
    settings: Settings | None = None,
    *,
    agent_deps: AgentDeps | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    install_log_masking()  # every log record is masked (Step 24)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            engine = create_app_engine(settings)
            stack.push_async_callback(engine.dispose)
            sessions = create_session_factory(engine)
            saver = checkpointer or await stack.enter_async_context(postgres_checkpointer(settings))
            deps = agent_deps or default_deps()
            if settings.api.schema_check_on_startup:
                await check_schema(settings, deps)
            agent = Agent(deps, saver)
            conversations = ConversationService(agent, sessions)
            tokens = TokenService(
                settings.jwt_secret_key.get_secret_value(), settings.auth,
                production=settings.app_env == "production",
            )  # fmt: skip
            auth = AuthService(sessions, tokens)
            limits = settings.api.rate_limits
            # Evaluation uses the same dependencies as the agent; production runs use the
            # pinned model (config/eval.yaml), tests keep their scripted model.
            evaluation = EvaluationService(
                sessions,
                lambda: EvalRunner(
                    sessions,
                    lambda: deps,
                    settings=settings,
                    make_llm=None if agent_deps else pinned_llm_factory(settings),
                ),
                preflight=None if agent_deps else lambda: require_llm_key(settings),
            )
            await evaluation.startup()
            stack.push_async_callback(evaluation.shutdown)
            app.state.auth = auth
            app.state.services = Services(
                api=settings.api,
                engine=engine,
                sessions=sessions,
                auth=auth,
                conversations=conversations,
                users=UserAdminService(sessions, settings.auth),
                feedback=FeedbackService(sessions),
                review=ReviewService(sessions, conversations),
                library=VerifiedLibraryService(sessions, agent.deps.load_semantic),
                metrics=MetricsService(sessions, settings.monitoring),
                evaluation=evaluation,
                cost_cap=DailyCostCap(sessions, settings.api.daily_cost_cap_usd),
                question_limiter=SlidingWindowLimiter(limits.questions_per_minute),
                login_limiter=SlidingWindowLimiter(limits.logins_per_minute_per_ip),
            )
            yield

    app = FastAPI(
        title=settings.app.name,
        version=settings.api.version,
        description="Governed text-to-SQL assistant for Northwind Traders (fictional data).",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    # Order matters: CORS is added last so it wraps everything, including error bodies.
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.api.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", HEADER],
        expose_headers=[HEADER],
    )
    app.include_router(public.router)
    app.include_router(questions.router)
    app.include_router(admin.router)
    return app
