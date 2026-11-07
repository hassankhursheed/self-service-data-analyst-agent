"""Agent runs, node steps, generated SQL, executions, blocks and errors."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

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
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (
    FINAL_STATUSES,
    BlockStage,
    Confidence,
    ErrorStatus,
    ExecutionStatus,
    NodeName,
    QueryKind,
    QuestionStatus,
    RegionCode,
)
from app.db.models.base import Base, CreatedAtMixin, TimestampMixin, check_in


class AgentRun(CreatedAtMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("question_id", "run_number"),
        check_in("final_status", FINAL_STATUSES, nullable=True),
        Index(None, "correlation_id"),
        Index(None, "started_at"),
        Index(None, "final_status", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    run_number: Mapped[int] = mapped_column(Integer, server_default="1")
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    graph_version: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(255))
    semantic_version: Mapped[str] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(128))
    final_status: Mapped[str | None] = mapped_column(String(32))
    total_latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0")
    langsmith_trace_url: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentStep(CreatedAtMixin, Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "seq"),
        check_in("node_name", NodeName),
        check_in("from_status", QuestionStatus, nullable=True),
        check_in("to_status", QuestionStatus),
        Index(None, "node_name", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    node_name: Mapped[str] = mapped_column(String(8))
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    # JSONB: each node has a different input/output shape (masked summaries only).
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GeneratedQuery(CreatedAtMixin, Base):
    __tablename__ = "generated_queries"
    __table_args__ = (
        UniqueConstraint("run_id", "attempt"),
        check_in("kind", QueryKind),
        Index(None, "kind", "run_id"),  # repair attempts per period (monitoring)
        check_in("confidence", Confidence, nullable=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    attempt: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    sql_text: Mapped[str] = mapped_column(Text)
    tables_used: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    metrics_used: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    confidence: Mapped[str | None] = mapped_column(String(8))
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    verified_query_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")


class QueryExecution(CreatedAtMixin, Base):
    __tablename__ = "query_executions"
    __table_args__ = (
        check_in("status", ExecutionStatus),
        check_in("region_code", RegionCode, nullable=True),
        Index(None, "generated_query_id"),
        Index(None, "status", "executed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    generated_query_id: Mapped[int] = mapped_column(
        ForeignKey("generated_queries.id", ondelete="CASCADE")
    )
    db_role: Mapped[str] = mapped_column(String(32))
    region_code: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    row_count: Mapped[int | None] = mapped_column(Integer)
    result_bytes: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BlockedQuery(CreatedAtMixin, Base):
    __tablename__ = "blocked_queries"
    __table_args__ = (
        check_in("stage", BlockStage),
        Index(None, "run_id"),
        Index(None, "reason_code", "created_at"),
        Index(None, "created_at"),  # blocked queries per period (monitoring)
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    # NULL when the question was blocked before any SQL was generated.
    generated_query_id: Mapped[int | None] = mapped_column(
        ForeignKey("generated_queries.id", ondelete="SET NULL")
    )
    stage: Mapped[str] = mapped_column(String(24))
    reason_code: Mapped[str] = mapped_column(String(64))
    reason_text: Mapped[str] = mapped_column(Text)


class AgentError(TimestampMixin, Base):
    __tablename__ = "agent_errors"
    __table_args__ = (
        check_in("status", ErrorStatus),
        check_in("node_name", NodeName, nullable=True),
        Index(None, "correlation_id"),
        Index(None, "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    node_name: Mapped[str | None] = mapped_column(String(8))
    error_type: Mapped[str] = mapped_column(String(64))
    retryable: Mapped[bool] = mapped_column(Boolean)
    error_message: Mapped[str] = mapped_column(Text)
    # JSONB: the logged input needed to re-run the question (masked).
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), server_default=ErrorStatus.OPEN.value)
