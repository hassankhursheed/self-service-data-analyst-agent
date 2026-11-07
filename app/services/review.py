"""Admin review: blocked queries, agent errors and re-running a failed question (brief §19).

A re-run uses the logged input (masked request) and runs it **as the original user**: the
user's current role, region and active flag are loaded from the database again, so a
re-run never gives more access than that user has today. Each error can be re-run once.
"""

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.conversations import ConversationService
from app.agent.state import AgentState
from app.auth.models import AuthenticatedUser
from app.auth.service import load_user
from app.core.enums import ErrorStatus
from app.core.errors import AppError
from app.db.models import (
    AgentError,
    AgentRun,
    AuditLog,
    BlockedQuery,
    Conversation,
    GeneratedQuery,
    Question,
    User,
)


class ErrorNotFound(AppError):
    code = "NOT_FOUND"
    user_message = "Error record not found."


class AlreadyRerun(AppError):
    code = "CONFLICT"
    user_message = "This error has already been re-run."


class CannotRerun(AppError):
    code = "CONFLICT"
    user_message = "This error has no logged question to re-run."


class Paged(BaseModel):
    model_config = ConfigDict(frozen=True)

    rows: list[dict[str, Any]]
    total: int


class RerunResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    error_id: int
    conversation_id: uuid.UUID
    question_id: uuid.UUID | None
    state: AgentState


async def _page(
    session: AsyncSession, query: Select[*tuple[Any, ...]], page: int, size: int
) -> Paged:
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    result = await session.execute(query.limit(size).offset((page - 1) * size))
    return Paged(rows=[dict(r._mapping) for r in result.all()], total=total)


class ReviewService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], conversations: ConversationService
    ) -> None:
        self.sessions = sessions
        self.conversations = conversations

    async def blocked(
        self, *, page: int, page_size: int, reason_code: str | None = None,
        date_from: dt.date | None = None, date_to: dt.date | None = None,
    ) -> Paged:  # fmt: skip
        query = (
            select(
                BlockedQuery.id,
                AgentRun.correlation_id,
                User.username,
                Question.role_name.label("role"),
                Question.question_text.label("question"),
                BlockedQuery.stage,
                BlockedQuery.reason_code,
                BlockedQuery.reason_text,
                GeneratedQuery.sql_text,
                BlockedQuery.created_at,
            )
            .join(AgentRun, AgentRun.id == BlockedQuery.run_id)
            .join(Question, Question.id == AgentRun.question_id)
            .outerjoin(User, User.id == Question.user_id)
            .outerjoin(GeneratedQuery, GeneratedQuery.id == BlockedQuery.generated_query_id)
            .order_by(BlockedQuery.created_at.desc(), BlockedQuery.id.desc())
        )
        if reason_code:
            query = query.where(BlockedQuery.reason_code == reason_code)
        if date_from:
            query = query.where(func.date(BlockedQuery.created_at) >= date_from)
        if date_to:
            query = query.where(func.date(BlockedQuery.created_at) <= date_to)
        async with self.sessions() as session:
            return await _page(session, query, page, page_size)

    async def errors(
        self, *, page: int, page_size: int, status: ErrorStatus | None = None,
        node_name: str | None = None,
    ) -> Paged:  # fmt: skip
        query = (
            select(
                AgentError.id,
                AgentError.correlation_id,
                AgentError.question_id,
                User.username,
                AgentError.node_name,
                AgentError.error_type,
                AgentError.retryable,
                AgentError.error_message,
                AgentError.status,
                AgentError.created_at,
            )
            .outerjoin(Question, Question.id == AgentError.question_id)
            .outerjoin(User, User.id == Question.user_id)
            .order_by(AgentError.created_at.desc(), AgentError.id.desc())
        )
        if status:
            query = query.where(AgentError.status == status.value)
        if node_name:
            query = query.where(AgentError.node_name == node_name)
        async with self.sessions() as session:
            return await _page(session, query, page, page_size)

    async def rerun(
        self, actor: AuthenticatedUser, error_id: int, correlation_id: uuid.UUID
    ) -> RerunResult:
        """Claim the error (open -> rerun) and run its logged question again."""
        async with self.sessions() as session, session.begin():
            error = await session.get(AgentError, error_id)
            if error is None:
                raise ErrorNotFound(f"agent error {error_id}")
            request = (error.input_snapshot or {}).get("request") or {}
            if not request.get("user_id") or not request.get("question"):
                raise CannotRerun(f"agent error {error_id} has no logged request")
            claimed = await session.execute(
                update(AgentError)
                .where(AgentError.id == error_id, AgentError.status == ErrorStatus.OPEN.value)
                .values(status=ErrorStatus.RERUN.value)
                .returning(AgentError.id)
            )
            if claimed.scalar() is None:
                raise AlreadyRerun(f"agent error {error_id} is {error.status}")
            _, original_user = await load_user(session, uuid.UUID(request["user_id"]))
            conversation_id = await self._own_conversation(
                session, original_user, request.get("conversation_id")
            )
            session.add(AuditLog(
                correlation_id=correlation_id, actor_user_id=actor.user_id,
                event_type="error_rerun", target_type="agent_error", target_id=str(error_id),
                details={"original_user": original_user.username,
                         "original_correlation_id": str(error.correlation_id)},
            ))  # fmt: skip
        if conversation_id is None:
            conversation_id = await self.conversations.start_conversation(
                original_user, request["question"]
            )
        state = await self.conversations.ask(
            original_user, request["question"], conversation_id, correlation_id=correlation_id
        )
        return RerunResult(
            error_id=error_id,
            conversation_id=conversation_id,
            question_id=await self.conversations.question_id_for(state),
            state=state,
        )

    @staticmethod
    async def _own_conversation(
        session: AsyncSession, user: AuthenticatedUser, conversation_id: str | None
    ) -> uuid.UUID | None:
        if not conversation_id:
            return None
        conversation = await session.get(Conversation, uuid.UUID(conversation_id))
        if conversation is None or conversation.user_id != user.user_id:
            return None
        return conversation.id
