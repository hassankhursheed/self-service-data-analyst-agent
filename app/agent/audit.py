"""Audit trail for one question (brief section 23), written by N-11.

``DatabaseAuditSink`` writes, in one transaction, everything needed to reconstruct a
question end to end: the question row, one ``agent_runs`` row, one ``agent_steps`` row per
node, every generated SQL, every execution, the block reason, clarifications, an audit-log
event and, for failures, an ``agent_errors`` row with the logged input for a re-run.
All free text and JSON written here is masked first (section 27).
"""

import datetime as dt
import logging
import uuid
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.state import AgentState
from app.core.enums import BlockStage, NodeName, QuestionStatus
from app.core.masking import mask_text, mask_value
from app.db.models import (
    AgentError,
    AgentRun,
    AgentStep,
    AuditLog,
    BlockedQuery,
    Clarification,
    Conversation,
    GeneratedQuery,
    QueryExecution,
    Question,
)

logger = logging.getLogger(__name__)


class AuditSink(Protocol):
    async def record(self, state: AgentState, *, audit_started: dt.datetime) -> None: ...


class MemoryAuditSink:
    """Keeps the states it was given (unit tests); can be told to fail."""

    def __init__(self, *, fail: bool = False) -> None:
        self.records: list[AgentState] = []
        self.fail = fail

    async def record(self, state: AgentState, *, audit_started: dt.datetime) -> None:
        if self.fail:
            raise RuntimeError("audit store unavailable")
        self.records.append(state)


def prompt_version_text(state: AgentState) -> str:
    return ",".join(f"{name}@{version}" for name, version in sorted(state.prompt_versions.items()))


def input_snapshot(state: AgentState) -> dict[str, Any]:
    """The logged input needed to re-run a failed question (masked)."""
    request = state.request.model_dump(mode="json")
    snapshot: dict[str, Any] = mask_value(
        {
            "request": request,
            "clarifications": [c.answer for c in state.clarifications if c.answer],
            "thread_id": state.thread_id,
        }
    )
    return snapshot


class DatabaseAuditSink:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, model_name: str,
                 trace_project: str) -> None:  # fmt: skip
        self.sessions = sessions
        self.model_name = model_name
        self.trace_project = trace_project

    async def record(self, state: AgentState, *, audit_started: dt.datetime) -> None:
        if state.request.user_id is None or state.correlation_id is None:
            logger.warning("audit skipped: no user id or correlation id in the request")
            return
        async with self.sessions() as session, session.begin():
            question = await self._question(session, state)
            run = await self._run(session, state, question)
            await self._steps(session, state, run, audit_started)
            query_ids = await self._queries(session, state, run)
            await self._executions(session, state, query_ids)
            await self._blocked(session, state, run, query_ids)
            await self._clarifications(session, state, question)
            self._finish_question(state, question)
            session.add(
                AuditLog(
                    correlation_id=state.correlation_id,
                    actor_user_id=state.request.user_id,
                    event_type=f"question_{(state.status or QuestionStatus.FAILED).value.lower()}",
                    target_type="question",
                    target_id=str(question.id),
                    details=mask_value(
                        {
                            "run_id": str(run.id),
                            "status": state.status.value if state.status else None,
                            "block_reason": state.block_reason.value
                            if state.block_reason
                            else None,
                            "row_count": state.execution.row_count if state.execution else None,
                            "role": state.request.role.value if state.request.role else None,
                            "region": state.request.region.value if state.request.region else None,
                        }
                    ),
                )
            )
            if state.status is QuestionStatus.FAILED or state.error is not None:
                session.add(
                    AgentError(
                        correlation_id=state.correlation_id,
                        question_id=question.id,
                        run_id=run.id,
                        node_name=state.error.node.value if state.error else None,
                        error_type=state.error.code if state.error else "FAILED",
                        retryable=state.error.retryable if state.error else False,
                        error_message=mask_text(state.error.detail if state.error else "failed")[
                            :4000
                        ],
                        input_snapshot=input_snapshot(state),
                    )
                )

    async def _question(self, session: AsyncSession, state: AgentState) -> Question:
        question = await session.scalar(
            select(Question).where(Question.correlation_id == state.correlation_id)
        )
        if question is not None:
            return question
        conversation_id = state.request.conversation_id
        if conversation_id is None or await session.get(Conversation, conversation_id) is None:
            conversation = Conversation(
                user_id=state.request.user_id, title=mask_text(state.question)[:80] or "Question"
            )
            session.add(conversation)
            await session.flush()
            conversation_id = conversation.id
        question = Question(
            correlation_id=state.correlation_id,
            conversation_id=conversation_id,
            user_id=state.request.user_id,
            question_text=mask_text(state.question or state.request.question)[:4000],
            role_name=state.request.role.value if state.request.role else None,
            region_code=state.request.region.value if state.request.region else None,
            status=(state.status or QuestionStatus.RECEIVED).value,
        )
        session.add(question)
        await session.flush()
        return question

    async def _run(self, session: AsyncSession, state: AgentState, question: Question) -> AgentRun:
        previous = await session.scalar(
            select(func.count(AgentRun.id)).where(AgentRun.question_id == question.id)
        )
        started = state.steps[0].started_at if state.steps else dt.datetime.now(dt.UTC)
        finished = dt.datetime.now(dt.UTC)
        run = AgentRun(
            question_id=question.id,
            run_number=(previous or 0) + 1,
            correlation_id=state.correlation_id,
            graph_version=state.graph_version,
            prompt_version=prompt_version_text(state),
            semantic_version=str(state.semantic.version) if state.semantic else "",
            model_name=self.model_name,
            final_status=state.status.value if state.status in _FINAL else None,
            total_latency_ms=int((finished - started).total_seconds() * 1000),
            input_tokens=state.usage.input_tokens,
            output_tokens=state.usage.output_tokens,
            estimated_cost_usd=state.usage.cost_usd,
            langsmith_trace_url=f"langsmith:{self.trace_project}/runs/{state.correlation_id}",
            started_at=started,
            finished_at=finished,
        )
        session.add(run)
        await session.flush()
        return run

    async def _steps(
        self, session: AsyncSession, state: AgentState, run: AgentRun, audit_started: dt.datetime
    ) -> None:
        for seq, step in enumerate(state.steps, 1):
            session.add(
                AgentStep(
                    run_id=run.id,
                    seq=seq,
                    node_name=step.node.value,
                    from_status=step.from_status.value if step.from_status else None,
                    to_status=(step.to_status or QuestionStatus.FAILED).value,
                    input_summary=mask_value(step.input_summary),
                    output_summary=mask_value(step.output_summary),
                    latency_ms=int(step.duration_ms),
                    error_code=step.error_code,
                    started_at=step.started_at,
                )
            )
        final = (state.status or QuestionStatus.FAILED).value
        session.add(
            AgentStep(
                run_id=run.id,
                seq=len(state.steps) + 1,
                node_name=NodeName.AUDIT.value,
                from_status=final,
                to_status=final,
                input_summary={"status": final},
                output_summary={"audit": "written"},
                latency_ms=int((dt.datetime.now(dt.UTC) - audit_started).total_seconds() * 1000),
                started_at=audit_started,
            )
        )

    async def _queries(
        self, session: AsyncSession, state: AgentState, run: AgentRun
    ) -> dict[int, int]:
        ids: dict[int, int] = {}
        for attempt in state.sql_attempts:
            row = GeneratedQuery(
                run_id=run.id,
                attempt=attempt.attempt,
                kind=attempt.kind.value,
                sql_text=mask_text(attempt.sql),
                tables_used=attempt.tables_used,
                metrics_used=attempt.metrics_used,
                confidence=attempt.confidence.value,
                date_from=state.date_range.from_date if state.date_range else None,
                date_to=state.date_range.to_date if state.date_range else None,
                verified_query_ids=[_as_uuid(v) for v in attempt.verified_examples if _as_uuid(v)],
            )
            session.add(row)
            await session.flush()
            ids[attempt.attempt] = row.id
        return ids

    async def _executions(
        self, session: AsyncSession, state: AgentState, query_ids: dict[int, int]
    ) -> None:
        for execution in state.executions:
            query_id = query_ids.get(execution.attempt)
            if query_id is None:
                continue
            session.add(
                QueryExecution(
                    generated_query_id=query_id,
                    db_role=f"analytics_ro/{execution.view_schema}",
                    region_code=execution.region.value if execution.region else None,
                    status=execution.status.value,
                    row_count=execution.row_count,
                    result_bytes=execution.result_bytes,
                    latency_ms=execution.latency_ms,
                    error_message=mask_text(execution.error)[:4000] if execution.error else None,
                )
            )

    async def _blocked(
        self, session: AsyncSession, state: AgentState, run: AgentRun, query_ids: dict[int, int]
    ) -> None:
        blocked = state.blocked
        if blocked is None:
            return
        query_id = (
            query_ids.get(len(state.sql_attempts))
            if blocked.stage is BlockStage.SQL_VALIDATION
            else None
        )
        session.add(
            BlockedQuery(
                run_id=run.id,
                generated_query_id=query_id,
                stage=blocked.stage.value,
                reason_code=blocked.reason_code.value,
                reason_text=mask_text(blocked.reason_text),
            )
        )

    async def _clarifications(
        self, session: AsyncSession, state: AgentState, question: Question
    ) -> None:
        stored = await session.scalar(
            select(func.count(Clarification.id)).where(Clarification.question_id == question.id)
        )
        for record in state.clarifications[stored or 0 :]:
            session.add(
                Clarification(
                    question_id=question.id,
                    asked_text=mask_text(record.question),
                    options=[mask_text(o) for o in record.options],
                    answer_text=mask_text(record.answer) if record.answer else None,
                    answered_at=record.answered_at,
                )
            )

    @staticmethod
    def _finish_question(state: AgentState, question: Question) -> None:
        question.status = (state.status or QuestionStatus.FAILED).value
        question.assumptions = [mask_text(a) for a in state.assumptions]
        if state.date_range is not None:
            question.resolved_date_from = state.date_range.from_date
            question.resolved_date_to = state.date_range.to_date
        if state.status in _FINAL:
            question.completed_at = dt.datetime.now(dt.UTC)


_FINAL = {QuestionStatus.ANSWERED, QuestionStatus.BLOCKED, QuestionStatus.REJECTED,
          QuestionStatus.FAILED}  # fmt: skip


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
