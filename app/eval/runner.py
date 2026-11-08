"""Run evaluation cases through the real graph and store the results (brief §24).

Each run uses fixed settings, recorded in ``eval_runs`` (columns and ``settings``):
the pinned model version and temperature 0 (config/eval.yaml), the business reference
date, the graph and prompt versions, the semantic layer version and mode, whether
verified examples were used and a fingerprint of the verified library, and the cases
version. Every case runs as its test user (role and region from the database) through
the read-only analytics role. Evaluation questions are not written to the audit tables
(they would distort the Monitoring page); their results are in ``eval_results`` and, when
LangSmith is configured, in LangSmith.
"""

import asyncio
import dataclasses
import datetime as dt
import hashlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.audit import MemoryAuditSink
from app.agent.checkpoint import checkpoint_serializer
from app.agent.deps import AgentDeps
from app.agent.graph import Agent
from app.agent.state import AgentRequest, AgentState
from app.auth.service import load_user
from app.core.config import PROJECT_ROOT, Settings
from app.core.enums import CaseType, EvalRunStatus, ExpectedBehaviour
from app.core.errors import AppError
from app.core.llm import LLMClient, build_chat_model, get_llm_config
from app.core.yaml_config import load_yaml_model
from app.db.models import EvalCase, EvalDataset, EvalResult, EvalRun, User
from app.eval.cases import ANSWERABLE, EvalCaseDef, EvalCaseFile, load_cases
from app.eval.expected import CaseExpectation, ExpectedFile, load_expected
from app.eval.langsmith_sync import LangSmithClient, sync_run
from app.eval.scoring import CaseScore, actual_result, percentile, preview, score_case
from app.semantic.models import ColumnDef, SemanticLayer, TableDef

logger = logging.getLogger(__name__)
EVAL_CONFIG_FILE = PROJECT_ROOT / "config" / "eval.yaml"
SemanticMode = Literal["full", "names_only"]


class EvalTargets(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_accuracy: float
    clarification_rate: float
    unsafe_blocked_rate: float
    access_leaks: int
    ungrounded_answers: int


class EvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    model: str
    temperature: float = Field(ge=0, le=0)
    dataset: str
    pause_between_cases_seconds: float = Field(ge=0)
    targets: EvalTargets


def load_eval_config(path: Path = EVAL_CONFIG_FILE) -> EvalConfig:
    return load_yaml_model(path, EvalConfig)


@lru_cache
def get_eval_config() -> EvalConfig:
    return load_eval_config()


class EvalOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_name: str = Field(min_length=1, max_length=100)
    verified_examples_enabled: bool = True
    semantic_mode: SemanticMode = "full"
    case_ids: list[str] | None = None
    case_types: list[CaseType] | None = None
    started_by: uuid.UUID | None = None


class RunAlreadyActive(AppError):
    code = "CONFLICT"
    user_message = "An evaluation run is already in progress."


class EvalInputError(AppError):
    code = "VALIDATION_ERROR"
    user_message = "The evaluation could not start."


# --- the pinned model ----------------------------------------------------------------------

PLACEHOLDERS = {"", "CHANGE_ME"}


def require_llm_key(settings: Settings) -> None:
    key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    if key in PLACEHOLDERS:
        raise EvalInputError(
            "LLM_API_KEY missing",
            user_message="LLM_API_KEY is not set; evaluation needs the model.",
        )


def pinned_llm_factory(settings: Settings) -> Callable[[str, float], LLMClient]:
    """Build the agent's LLM client for the pinned evaluation model and temperature."""

    def make(model: str, temperature: float) -> LLMClient:
        config = get_llm_config().model_copy(update={"model": model, "temperature": temperature})
        return LLMClient(build_chat_model(config, settings.llm_api_key), config)

    return make


# --- experiment settings -----------------------------------------------------------------


def names_only_layer(layer: SemanticLayer) -> SemanticLayer:
    """The semantic layer without its business knowledge: table and column names only.

    Descriptions become the plain names, example values, metric definitions and synonyms
    are removed. Access rules (allowed roles) stay, so validation is unchanged."""
    tables = {
        name: TableDef(
            description=name,
            allowed_roles=table.allowed_roles,
            columns={
                col: ColumnDef(description=col, allowed_roles=c.allowed_roles)
                for col, c in table.columns.items()
            },
        )
        for name, table in layer.tables.items()
    }
    return SemanticLayer(
        version=layer.version, tables=tables, joins=layer.joins, metrics={}, synonyms={}
    )


def eval_deps(
    base: AgentDeps,
    options: EvalOptions,
    config: EvalConfig,
    make_llm: Callable[[str, float], Any] | None = None,
) -> AgentDeps:
    """The agent dependencies for one experiment."""
    agent_config = base.agent_config.model_copy(
        update={
            "verified_examples": base.agent_config.verified_examples.model_copy(
                update={"enabled": options.verified_examples_enabled}
            )
        }
    )
    llm_config = base.llm_config.model_copy(
        update={"model": config.model, "temperature": config.temperature}
    )
    load_semantic = base.load_semantic
    if options.semantic_mode == "names_only":
        original = base.load_semantic

        async def load_names_only() -> SemanticLayer:
            return names_only_layer(await original())

        load_semantic = load_names_only
    llm = make_llm(config.model, config.temperature) if make_llm else base.llm
    return dataclasses.replace(
        base,
        agent_config=agent_config,
        llm_config=llm_config,
        llm=llm,
        load_semantic=load_semantic,
        audit=MemoryAuditSink(),
    )


async def library_fingerprint(deps: AgentDeps) -> str:
    """Short hash of the enabled verified examples (lineage and version)."""
    try:
        examples = await deps.load_verified()
    except Exception:  # recorded as unknown rather than failing the run
        return "unavailable"
    text = ",".join(sorted(f"{e.lineage_id}:{e.version}" for e in examples))
    return f"{len(examples)}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"


# --- metrics -------------------------------------------------------------------------------


class RunMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    cases_total: int
    cases_passed: int
    execution_accuracy: float | None
    clarification_rate: float | None
    unsafe_blocked_rate: float | None
    access_control_pass_rate: float | None
    access_leaks: int
    ungrounded_answers: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    avg_cost_usd: float | None


class CaseOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    case: EvalCaseDef
    score: CaseScore
    status: str | None
    latency_ms: int
    cost_usd: float

    @property
    def case_id(self) -> str:
        return self.case.id

    @property
    def passed(self) -> bool:
        return self.score.passed

    @property
    def reason(self) -> str:
        return self.score.reason


def _rate(outcomes: list[CaseOutcome], types: tuple[CaseType, ...]) -> float | None:
    chosen = [o for o in outcomes if o.case.type in types]
    return round(sum(o.score.passed for o in chosen) / len(chosen), 4) if chosen else None


def compute_metrics(outcomes: list[CaseOutcome]) -> RunMetrics:
    latencies = [float(o.latency_ms) for o in outcomes]
    p50, p95 = percentile(latencies, 0.5), percentile(latencies, 0.95)
    answerable = [
        o for o in outcomes if o.case.expected_behaviour is ExpectedBehaviour.CORRECT_RESULT
    ]
    return RunMetrics(
        cases_total=len(outcomes),
        cases_passed=sum(o.score.passed for o in outcomes),
        execution_accuracy=(
            round(sum(o.score.passed for o in answerable) / len(answerable), 4)
            if answerable
            else None
        ),
        clarification_rate=_rate(outcomes, (CaseType.AMBIGUOUS,)),
        unsafe_blocked_rate=_rate(outcomes, (CaseType.UNSAFE,)),
        access_control_pass_rate=_rate(outcomes, (CaseType.ACCESS_CONTROL,)),
        access_leaks=sum(o.score.leaked for o in outcomes),
        ungrounded_answers=sum(o.score.ungrounded for o in outcomes),
        latency_p50_ms=round(p50, 1) if p50 is not None else None,
        latency_p95_ms=round(p95, 1) if p95 is not None else None,
        avg_cost_usd=round(sum(o.cost_usd for o in outcomes) / len(outcomes), 6)
        if outcomes
        else None,
    )


# --- the runner ----------------------------------------------------------------------------

Sleep = Callable[[float], Awaitable[None]]


class EvalRunner:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        base_deps: Callable[[], AgentDeps],
        *,
        config: EvalConfig | None = None,
        cases: EvalCaseFile | None = None,
        make_llm: Callable[[str, float], Any] | None = None,
        sleep: Sleep = asyncio.sleep,
        settings: Settings | None = None,
        langsmith_client: LangSmithClient = None,
    ) -> None:
        self.sessions = sessions
        self.base_deps = base_deps
        self.config = config or get_eval_config()
        self.cases = cases or load_cases()
        self.make_llm = make_llm
        self.sleep = sleep
        # LangSmith upload: only when settings (or a client, in tests) are given.
        self.settings = settings
        self.langsmith_client = langsmith_client

    async def _dataset(self, session: AsyncSession) -> EvalDataset:
        dataset = await session.scalar(
            select(EvalDataset).where(
                EvalDataset.name == self.config.dataset, EvalDataset.version == self.cases.version
            )
        )
        if dataset is None:
            dataset = EvalDataset(
                name=self.config.dataset, version=self.cases.version, file_path="eval/cases.yaml"
            )
            session.add(dataset)
            await session.flush()
        existing = {
            c.case_key: c
            for c in await session.scalars(
                select(EvalCase).where(EvalCase.dataset_id == dataset.id)
            )
        }
        for case in self.cases.cases:
            row = existing.get(case.id) or EvalCase(dataset_id=dataset.id, case_key=case.id)
            row.case_type = case.type.value
            row.test_username = case.test_user
            row.question = case.question
            row.expected_behaviour = case.expected_behaviour.value
            row.expected_sql = case.expected_sql
            session.add(row)
        await session.flush()
        return dataset

    async def create_run(self, options: EvalOptions) -> uuid.UUID:
        """Record a new run (status running) and return its ID; ``execute`` does the work."""
        selected = self.cases.select(options.case_ids, options.case_types)
        if not selected:
            raise EvalInputError("no cases selected", user_message="No cases match the selection.")
        load_expected(self.cases.version)  # fail early when the expected results are missing
        deps = eval_deps(self.base_deps(), options, self.config, self.make_llm)
        layer = await deps.load_semantic()
        async with self.sessions() as session, session.begin():
            active = await session.scalar(
                select(EvalRun.id).where(EvalRun.status == EvalRunStatus.RUNNING.value)
            )
            if active is not None:
                raise RunAlreadyActive(f"run {active} is running")
            dataset = await self._dataset(session)
            run = EvalRun(
                dataset_id=dataset.id,
                experiment_name=options.experiment_name,
                model_name=self.config.model,
                temperature=Decimal(str(self.config.temperature)),
                graph_version=deps.agent_config.graph_version,
                prompt_version=",".join(
                    f"{k}@{v}" for k, v in sorted(deps.llm_config.prompts.items())
                ),
                semantic_version=f"{layer.version}:{options.semantic_mode}",
                verified_examples_enabled=options.verified_examples_enabled,
                reference_date=deps.calendar.reference_date,
                status=EvalRunStatus.RUNNING.value,
                started_by=options.started_by,
                cases_total=len(selected),
                settings={
                    "cases_version": self.cases.version,
                    "eval_config_version": self.config.version,
                    "llm_config_version": deps.llm_config.version,
                    "semantic_mode": options.semantic_mode,
                    "verified_library": await library_fingerprint(deps),
                    "case_ids": [c.id for c in selected],
                    "provider": deps.llm_config.provider,
                },
            )
            session.add(run)
            await session.flush()
            return run.id

    async def _user_request(self, session: AsyncSession, case: EvalCaseDef) -> AgentRequest:
        user_id = await session.scalar(select(User.id).where(User.username == case.test_user))
        if user_id is None:
            raise EvalInputError(f"unknown test user {case.test_user}")
        _, user = await load_user(session, user_id)
        return AgentRequest(
            username=user.username,
            role=user.role,
            region=user.region,
            is_active=user.is_active,
            question=case.question,
            user_id=uuid.UUID(str(user.user_id)),  # plain UUID: checkpoints refuse driver types
            correlation_id=uuid.uuid4(),
        )

    async def execute(
        self,
        run_id: uuid.UUID,
        options: EvalOptions,
        on_case: Callable[[CaseOutcome], None] | None = None,
    ) -> RunMetrics | None:
        """Run every selected case, store each result, then the run's metrics."""
        try:
            expected = load_expected(self.cases.version)
            deps = eval_deps(self.base_deps(), options, self.config, self.make_llm)
            agent = Agent(deps, InMemorySaver(serde=checkpoint_serializer()))
            async with self.sessions() as session:
                case_ids = dict(
                    (
                        await session.execute(
                            select(EvalCase.case_key, EvalCase.id)
                            .join(EvalRun, EvalRun.dataset_id == EvalCase.dataset_id)
                            .where(EvalRun.id == run_id)
                        )
                    ).all()
                )
            outcomes: list[CaseOutcome] = []
            selected = self.cases.select(options.case_ids, options.case_types)
            for index, case in enumerate(selected):
                if index and self.config.pause_between_cases_seconds:
                    await self.sleep(self.config.pause_between_cases_seconds)
                outcome = await self._run_case(
                    agent, run_id, case, expected.cases[case.id], case_ids[case.id]
                )
                outcomes.append(outcome)
                if on_case:
                    on_case(outcome)
            metrics = compute_metrics(outcomes)
            await self._finish(run_id, EvalRunStatus.COMPLETED, metrics)
            await self._langsmith(run_id, options, outcomes, expected, metrics)
            return metrics
        except Exception as exc:
            logger.exception("evaluation run %s failed", run_id)
            await self._finish(run_id, EvalRunStatus.FAILED, None, f"{type(exc).__name__}: {exc}")
            return None

    async def _run_case(
        self,
        agent: Agent,
        run_id: uuid.UUID,
        case: EvalCaseDef,
        expectation: CaseExpectation,
        case_db_id: int,
    ) -> CaseOutcome:
        async with self.sessions() as session:
            request = await self._user_request(session, case)
        started = time.perf_counter()
        state: AgentState | None = None
        error: str | None = None
        try:
            state = await agent.run(request, thread_id=f"eval:{run_id}:{case.id}")
        except Exception as exc:  # a crash is a failed case, not a failed run
            error = f"{type(exc).__name__}: {exc}"
        latency = int((time.perf_counter() - started) * 1000)
        if state is None:
            score = CaseScore(passed=False, reason=f"agent error: {error}")
            status, cost = None, 0.0
            details: dict[str, Any] = {"error": error}
        else:
            score = score_case(case, expectation, state)
            status = state.status.value if state.status else None
            cost = state.usage.cost_usd
            details = {
                "question": case.question,
                "test_user": case.test_user,
                "expected_behaviour": case.expected_behaviour.value,
                "status": status,
                "block_reason": state.block_reason.value if state.block_reason else None,
                "sql": state.executed_sql
                or (state.sql_attempts[-1].sql if state.sql_attempts else None),
                "answer": state.answer.text if state.answer else state.user_message,
                "clarification": (
                    state.pending_clarification.question if state.pending_clarification else None
                ),
                "expected": preview(expectation.expected or expectation.truth),
                "actual": preview(actual_result(state)),
                "ungrounded_numbers": score.ungrounded_numbers,
                "verified_examples": [str(e.id) for e in state.verified_examples],
                "tokens": state.usage.input_tokens + state.usage.output_tokens,
            }
        async with self.sessions() as session, session.begin():
            session.add(
                EvalResult(
                    run_id=run_id,
                    case_id=case_db_id,
                    passed=score.passed,
                    final_status=status,
                    failure_reason=None if score.passed else score.reason,
                    latency_ms=latency,
                    cost_usd=Decimal(str(round(cost, 6))),
                    correlation_id=request.correlation_id,
                    leaked=score.leaked,
                    ungrounded=score.ungrounded,
                    details=details,
                )
            )
        return CaseOutcome(case=case, score=score, status=status, latency_ms=latency, cost_usd=cost)

    async def _langsmith(
        self,
        run_id: uuid.UUID,
        options: EvalOptions,
        outcomes: list[CaseOutcome],
        expected: ExpectedFile,
        metrics: RunMetrics,
    ) -> None:
        if self.settings is None and self.langsmith_client is None:
            return
        async with self.sessions() as session:
            run = await session.get(EvalRun, run_id)
            metadata = dict(run.settings) if run else {}
        metadata.update(
            experiment=options.experiment_name,
            model=self.config.model,
            **{k: v for k, v in metrics.model_dump().items() if v is not None},
        )
        info = await asyncio.to_thread(
            sync_run,
            self.settings,
            self.config.dataset,
            self.cases,
            expected,
            options.experiment_name,
            run_id,
            outcomes,
            metadata,
            self.langsmith_client,
        )
        async with self.sessions() as session, session.begin():
            run = await session.get(EvalRun, run_id)
            if run is not None:
                run.settings = {**run.settings, "langsmith": info}
                if info.get("dataset_id"):
                    dataset = await session.get(EvalDataset, run.dataset_id)
                    if dataset is not None:
                        dataset.langsmith_dataset_id = str(info["dataset_id"])[:64]

    async def _finish(
        self,
        run_id: uuid.UUID,
        status: EvalRunStatus,
        metrics: RunMetrics | None,
        error: str | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": status.value,
            "finished_at": dt.datetime.now(dt.UTC),
            "error_message": error,
        }
        if metrics is not None:

            def dec(v: float | None) -> Decimal | None:
                return Decimal(str(v)) if v is not None else None

            values.update(
                cases_passed=metrics.cases_passed,
                execution_accuracy=dec(metrics.execution_accuracy),
                clarification_rate=dec(metrics.clarification_rate),
                unsafe_blocked_rate=dec(metrics.unsafe_blocked_rate),
                access_leaks=metrics.access_leaks,
                ungrounded_answers=metrics.ungrounded_answers,
                latency_p50_ms=int(metrics.latency_p50_ms)
                if metrics.latency_p50_ms is not None
                else None,
                latency_p95_ms=int(metrics.latency_p95_ms)
                if metrics.latency_p95_ms is not None
                else None,
                avg_cost_usd=dec(metrics.avg_cost_usd),
            )
        async with self.sessions() as session, session.begin():
            await session.execute(update(EvalRun).where(EvalRun.id == run_id).values(**values))

    async def mark_interrupted(self) -> int:
        """Runs left 'running' by a stopped process are marked failed (called at startup)."""
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                update(EvalRun)
                .where(EvalRun.status == EvalRunStatus.RUNNING.value)
                .values(
                    status=EvalRunStatus.FAILED.value,
                    finished_at=dt.datetime.now(dt.UTC),
                    error_message="interrupted: the service stopped during the run",
                )
            )
            return int(getattr(result, "rowcount", 0) or 0)


__all__ = ["ANSWERABLE", "EvalOptions", "EvalRunner", "RunMetrics", "compute_metrics"]
