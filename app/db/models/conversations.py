"""Conversations, questions, clarifications and feedback."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import QuestionStatus, Rating, RegionCode, ReviewStatus, RoleName
from app.db.models.base import Base, CreatedAtMixin, TimestampMixin, check_in


class Conversation(TimestampMixin, Base):
    """The id doubles as the LangGraph checkpointer thread id."""

    __tablename__ = "conversations"
    __table_args__ = (Index(None, "user_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    is_archived: Mapped[bool] = mapped_column(Boolean, server_default=false())


class Question(TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (
        check_in("status", QuestionStatus),
        check_in("role_name", RoleName, nullable=True),
        check_in("region_code", RegionCode, nullable=True),
        Index(None, "conversation_id", "created_at"),
        Index(None, "status", "created_at"),
        Index(None, "user_id", "created_at"),
        Index(None, "created_at"),  # questions per period (monitoring)
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    parent_question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL")
    )
    question_text: Mapped[str] = mapped_column(Text)
    role_name: Mapped[str | None] = mapped_column(String(32))
    region_code: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), server_default=QuestionStatus.RECEIVED.value)
    resolved_date_from: Mapped[date | None] = mapped_column(Date)
    resolved_date_to: Mapped[date | None] = mapped_column(Date)
    assumptions: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Clarification(CreatedAtMixin, Base):
    __tablename__ = "clarifications"
    # created_at: clarifications asked per period (monitoring).
    __table_args__ = (Index(None, "question_id"), Index(None, "created_at"))

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    asked_text: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    answer_text: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Feedback(TimestampMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("question_id", "user_id"),
        check_in("rating", Rating),
        check_in("review_status", ReviewStatus),
        Index(None, "rating", "review_status"),
        Index(None, "updated_at"),  # ratings per period (monitoring)
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # The run that produced the rated answer (latest run of the question).
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    rating: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(16), server_default=ReviewStatus.OPEN.value)
