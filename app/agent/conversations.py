"""Conversations: user-scoped threads, follow-up history and the app tables (brief §18).

- A conversation belongs to one user (``app.conversations``). Its LangGraph thread ID is
  ``user:<user id>:conversation:<conversation id>``; it is only ever built after the
  conversation's owner has been checked, so one user can never load another user's thread.
- Every question, new or follow-up, runs the whole graph again (guardrails, validation,
  access rules). Only a short history of earlier questions is carried over.
- Each question is stored in ``app.questions`` and updated when it finishes.
"""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.graph import Agent
from app.agent.state import AgentRequest, AgentState, ConversationTurn
from app.auth.models import AuthenticatedUser
from app.core.enums import FINAL_STATUSES, QuestionStatus
from app.core.errors import AppError
from app.core.masking import mask_text
from app.db.models import Conversation, Question

MAX_HISTORY_TURNS = 5
TITLE_LENGTH = 80


class ConversationNotFound(AppError):
    code = "NOT_FOUND"
    user_message = "Conversation not found."


class NoPendingClarification(AppError):
    code = "NO_PENDING_CLARIFICATION"
    user_message = "This conversation is not waiting for a clarification."


class ConversationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    title: str
    created_at: dt.datetime
    updated_at: dt.datetime
    question_count: int


class QuestionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    correlation_id: uuid.UUID
    question: str
    status: str
    created_at: dt.datetime


class ConversationDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    title: str
    questions: list[QuestionSummary]


def thread_id_for(user_id: uuid.UUID, conversation_id: uuid.UUID) -> str:
    return f"user:{user_id}:conversation:{conversation_id}"


def turn_from_state(state: AgentState) -> ConversationTurn:
    return ConversationTurn(
        question=state.question or state.request.question,
        interpreted_question=state.interpreted_question or state.question or state.request.question,
        status=state.status,
        sql=state.executed_sql,
        date_range_label=state.date_range.label if state.date_range else None,
    )


class ConversationService:
    def __init__(self, agent: Agent, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.agent = agent
        self.sessions = sessions

    # --- conversations -------------------------------------------------------------------

    async def start_conversation(self, user: AuthenticatedUser, title: str = "") -> uuid.UUID:
        async with self.sessions() as session, session.begin():
            conversation = Conversation(
                user_id=user.user_id, title=mask_text(title)[:TITLE_LENGTH] or "New conversation"
            )
            session.add(conversation)
            await session.flush()
            return conversation.id

    async def _owned(
        self, session: AsyncSession, user: AuthenticatedUser, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user.user_id:
            raise ConversationNotFound(f"conversation {conversation_id} not found for this user")
        return conversation

    async def list_conversations(self, user: AuthenticatedUser) -> list[ConversationSummary]:
        async with self.sessions() as session:
            count = func.count(Question.id)
            rows = await session.execute(
                select(Conversation, count)
                .outerjoin(Question, Question.conversation_id == Conversation.id)
                .where(Conversation.user_id == user.user_id)
                .group_by(Conversation.id)
                .order_by(Conversation.updated_at.desc())
            )
            return [
                ConversationSummary(
                    id=c.id,
                    title=c.title,
                    created_at=c.created_at,
                    updated_at=c.updated_at,
                    question_count=n,
                )
                for c, n in rows.all()
            ]

    async def open_conversation(
        self, user: AuthenticatedUser, conversation_id: uuid.UUID
    ) -> ConversationDetail:
        async with self.sessions() as session:
            conversation = await self._owned(session, user, conversation_id)
            questions = await session.scalars(
                select(Question)
                .where(Question.conversation_id == conversation.id)
                .order_by(Question.created_at)
            )
            return ConversationDetail(
                id=conversation.id,
                title=conversation.title,
                questions=[
                    QuestionSummary(
                        id=q.id,
                        correlation_id=q.correlation_id,
                        question=q.question_text,
                        status=q.status,
                        created_at=q.created_at,
                    )
                    for q in questions
                ],
            )

    # --- questions -----------------------------------------------------------------------

    async def ask(
        self,
        user: AuthenticatedUser,
        question: str,
        conversation_id: uuid.UUID | None = None,
        *,
        correlation_id: uuid.UUID | None = None,
    ) -> AgentState:
        """Ask a new question, or a follow-up when ``conversation_id`` is given.

        ``correlation_id`` is the API request's ID, so the HTTP response, the audit rows and
        the trace share one ID."""
        if conversation_id is None:
            conversation_id = await self.start_conversation(user, question)
        async with self.sessions() as session:
            await self._owned(session, user, conversation_id)
        thread_id = thread_id_for(user.user_id, conversation_id)
        history = await self._history(thread_id)
        correlation_id = correlation_id or uuid.uuid4()
        question_id = await self._record_question(user, conversation_id, correlation_id, question)
        request = AgentRequest(
            username=user.username,
            role=user.role,
            region=user.region,
            is_active=user.is_active,
            question=question,
            user_id=user.user_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
        )
        state = await self.agent.run(request, thread_id=thread_id, history=history)
        await self._finish_question(question_id, state)
        return state

    async def clarify(
        self, user: AuthenticatedUser, conversation_id: uuid.UUID, reply: str
    ) -> AgentState:
        """Answer the pending clarifying question of the user's own conversation."""
        async with self.sessions() as session:
            await self._owned(session, user, conversation_id)
        thread_id = thread_id_for(user.user_id, conversation_id)
        if not await self.agent.has_thread(thread_id):
            raise NoPendingClarification(f"no thread for conversation {conversation_id}")
        if not (await self.agent.state(thread_id)).awaiting_reply:
            raise NoPendingClarification(f"conversation {conversation_id} is not paused")
        state = await self.agent.resume(thread_id, reply)
        question_id = await self.question_id_for(state)
        if question_id is not None:
            await self._finish_question(question_id, state)
        return state

    async def _history(self, thread_id: str) -> list[ConversationTurn]:
        if not await self.agent.has_thread(thread_id):
            return []
        previous = await self.agent.state(thread_id)
        if previous.status is None or previous.awaiting_reply:
            return list(previous.history)
        return [*previous.history, turn_from_state(previous)][-MAX_HISTORY_TURNS:]

    async def _record_question(
        self,
        user: AuthenticatedUser,
        conversation_id: uuid.UUID,
        correlation_id: uuid.UUID,
        text: str,
    ) -> uuid.UUID:
        async with self.sessions() as session, session.begin():
            question = Question(
                correlation_id=correlation_id,
                conversation_id=conversation_id,
                user_id=user.user_id,
                question_text=mask_text(text)[:4000],
                role_name=user.role.value if user.role else None,
                region_code=user.region.value if user.region else None,
                status=QuestionStatus.RECEIVED.value,
            )
            session.add(question)
            conversation = await session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.updated_at = dt.datetime.now(dt.UTC)
            await session.flush()
            return question.id

    async def latest_state(
        self, user: AuthenticatedUser, conversation_id: uuid.UUID
    ) -> AgentState | None:
        """The checkpointed state of the conversation's latest question (owner only)."""
        async with self.sessions() as session:
            await self._owned(session, user, conversation_id)
        thread_id = thread_id_for(user.user_id, conversation_id)
        if not await self.agent.has_thread(thread_id):
            return None
        return await self.agent.state(thread_id)

    async def question_id_for(self, state: AgentState) -> uuid.UUID | None:
        if state.correlation_id is None:
            return None
        async with self.sessions() as session:
            return await session.scalar(
                select(Question.id).where(Question.correlation_id == state.correlation_id)
            )

    async def _finish_question(self, question_id: uuid.UUID, state: AgentState) -> None:
        async with self.sessions() as session, session.begin():
            question = await session.get(Question, question_id)
            if question is None:
                return
            question.status = (state.status or QuestionStatus.FAILED).value
            question.assumptions = list(state.assumptions)
            if state.date_range is not None:
                question.resolved_date_from = state.date_range.from_date
                question.resolved_date_to = state.date_range.to_date
            if state.status in FINAL_STATUSES:
                question.completed_at = dt.datetime.now(dt.UTC)
