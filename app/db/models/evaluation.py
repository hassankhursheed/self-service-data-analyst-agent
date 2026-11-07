"""Evaluation datasets, cases, runs and results."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import FINAL_STATUSES, CaseType, EvalRunStatus, ExpectedBehaviour
from app.db.models.base import Base, CreatedAtMixin, TimestampMixin, check_in


class EvalDataset(CreatedAtMixin, Base):
    __tablename__ = "eval_datasets"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(Text)
    langsmith_dataset_id: Mapped[str | None] = mapped_column(String(64))


class EvalCase(TimestampMixin, Base):
    __tablename__ = "eval_cases"
    __table_args__ = (
        UniqueConstraint("dataset_id", "case_key"),
        check_in("case_type", CaseType),
        check_in("expected_behaviour", ExpectedBehaviour),
        Index(None, "case_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("eval_datasets.id", ondelete="CASCADE"))
    case_key: Mapped[str] = mapped_column(String(32))
    case_type: Mapped[str] = mapped_column(String(16))
    test_username: Mapped[str] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(Text)
    expected_behaviour: Mapped[str] = mapped_column(String(16))
    expected_sql: Mapped[str | None] = mapped_column(Text)
    source_feedback_id: Mapped[int | None] = mapped_column(
        ForeignKey("feedback.id", ondelete="SET NULL")
    )


class EvalRun(TimestampMixin, Base):
    """Settings are recorded with every run so results are repeatable (brief section 24)."""

    __tablename__ = "eval_runs"
    __table_args__ = (
        check_in("status", EvalRunStatus),
        Index(None, "started_at"),
        Index(None, "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    dataset_id: Mapped[int] = mapped_column(ForeignKey("eval_datasets.id", ondelete="RESTRICT"))
    experiment_name: Mapped[str] = mapped_column(String(100))
    model_name: Mapped[str] = mapped_column(String(128))
    temperature: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    graph_version: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(255))
    semantic_version: Mapped[str] = mapped_column(String(32))
    verified_examples_enabled: Mapped[bool] = mapped_column(Boolean)
    reference_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), server_default=EvalRunStatus.RUNNING.value)
    execution_accuracy: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    clarification_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    unsafe_blocked_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    access_leaks: Mapped[int | None] = mapped_column(Integer)
    ungrounded_answers: Mapped[int | None] = mapped_column(Integer)
    latency_p50_ms: Mapped[int | None] = mapped_column(Integer)
    latency_p95_ms: Mapped[int | None] = mapped_column(Integer)
    avg_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvalResult(CreatedAtMixin, Base):
    __tablename__ = "eval_results"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id"),
        check_in("final_status", FINAL_STATUSES, nullable=True),
        Index(None, "passed"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"))
    case_id: Mapped[int] = mapped_column(ForeignKey("eval_cases.id", ondelete="CASCADE"))
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL")
    )
    passed: Mapped[bool] = mapped_column(Boolean)
    final_status: Mapped[str | None] = mapped_column(String(32))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
