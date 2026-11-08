"""Evaluation runs started from the admin area (brief §24).

A run is recorded first (so the API can answer 202 with its ID at once) and then executed
as a background task in the API process; only one run may be active. Runs left
``running`` by a stopped process are marked failed at startup.
"""

import asyncio
import datetime as dt
import logging
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuthenticatedUser
from app.core.errors import AppError
from app.db.models import EvalCase, EvalResult, EvalRun
from app.eval.runner import EvalOptions, EvalRunner

logger = logging.getLogger(__name__)


class EvalRunNotFound(AppError):
    code = "NOT_FOUND"
    user_message = "Evaluation run not found."


class RunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID
    experiment_name: str
    model_name: str
    status: str
    semantic_version: str
    verified_examples_enabled: bool
    cases_total: int | None
    cases_passed: int | None
    execution_accuracy: Decimal | None
    clarification_rate: Decimal | None
    unsafe_blocked_rate: Decimal | None
    access_leaks: int | None
    ungrounded_answers: int | None
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    avg_cost_usd: Decimal | None
    started_at: dt.datetime
    finished_at: dt.datetime | None
    error_message: str | None
    settings: dict[str, Any]
    progress: int


class CaseResultView(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_key: str
    case_type: str
    question: str
    test_user: str
    expected_behaviour: str
    passed: bool
    final_status: str | None
    failure_reason: str | None
    leaked: bool
    ungrounded: bool
    latency_ms: int | None
    cost_usd: Decimal | None
    details: dict[str, Any]


class RunDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    run: RunSummary
    results: list[CaseResultView]


def _summary(run: EvalRun, progress: int) -> RunSummary:
    return RunSummary(
        run_id=run.id,
        experiment_name=run.experiment_name,
        model_name=run.model_name,
        status=run.status,
        semantic_version=run.semantic_version,
        verified_examples_enabled=run.verified_examples_enabled,
        cases_total=run.cases_total,
        cases_passed=run.cases_passed,
        execution_accuracy=run.execution_accuracy,
        clarification_rate=run.clarification_rate,
        unsafe_blocked_rate=run.unsafe_blocked_rate,
        access_leaks=run.access_leaks,
        ungrounded_answers=run.ungrounded_answers,
        latency_p50_ms=run.latency_p50_ms,
        latency_p95_ms=run.latency_p95_ms,
        avg_cost_usd=run.avg_cost_usd,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_message=run.error_message,
        settings=dict(run.settings),
        progress=progress,
    )


class EvaluationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        runner_factory: Callable[[], EvalRunner],
        preflight: Callable[[], None] | None = None,
    ) -> None:
        self.sessions = sessions
        self.runner_factory = runner_factory
        self.preflight = preflight
        self._tasks: set[asyncio.Task[Any]] = set()

    async def startup(self) -> None:
        marked = await self.runner_factory().mark_interrupted()
        if marked:
            logger.warning("marked %d interrupted evaluation run(s) as failed", marked)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def start(self, actor: AuthenticatedUser, options: EvalOptions) -> uuid.UUID:
        if self.preflight is not None:
            self.preflight()
        runner = self.runner_factory()
        options = options.model_copy(update={"started_by": actor.user_id})
        run_id = await runner.create_run(options)
        task = asyncio.create_task(runner.execute(run_id, options), name=f"eval-{run_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run_id

    async def wait(self) -> None:
        """Wait for running evaluations (tests)."""
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _progress(
        self, session: AsyncSession, run_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        if not run_ids:
            return {}
        rows = await session.execute(
            select(EvalResult.run_id, func.count(EvalResult.id))
            .where(EvalResult.run_id.in_(run_ids))
            .group_by(EvalResult.run_id)
        )
        return dict(rows.all())

    async def list_runs(self, *, page: int, page_size: int) -> tuple[list[RunSummary], int]:
        async with self.sessions() as session:
            total = await session.scalar(select(func.count(EvalRun.id))) or 0
            runs = list(
                await session.scalars(
                    select(EvalRun)
                    .order_by(EvalRun.started_at.desc())
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
            )
            progress = await self._progress(session, [r.id for r in runs])
            return [_summary(r, progress.get(r.id, 0)) for r in runs], total

    async def get_run(self, run_id: uuid.UUID) -> RunDetail:
        async with self.sessions() as session:
            run = await session.get(EvalRun, run_id)
            if run is None:
                raise EvalRunNotFound(str(run_id))
            rows = await session.execute(
                select(EvalResult, EvalCase)
                .join(EvalCase, EvalCase.id == EvalResult.case_id)
                .where(EvalResult.run_id == run_id)
                .order_by(EvalResult.passed, EvalCase.case_key)
            )
            results = [
                CaseResultView(
                    case_key=case.case_key,
                    case_type=case.case_type,
                    question=case.question,
                    test_user=case.test_username,
                    expected_behaviour=case.expected_behaviour,
                    passed=res.passed,
                    final_status=res.final_status,
                    failure_reason=res.failure_reason,
                    leaked=res.leaked,
                    ungrounded=res.ungrounded,
                    latency_ms=res.latency_ms,
                    cost_usd=res.cost_usd,
                    details=dict(res.details),
                )
                for res, case in rows.all()
            ]
            return RunDetail(run=_summary(run, len(results)), results=results)
