"""Audit log and alerts."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AlertChannel
from app.db.models.base import Base, CreatedAtMixin, check_in


class AuditLog(CreatedAtMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index(None, "occurred_at"),
        Index(None, "event_type", "occurred_at"),
        Index(None, "correlation_id"),
        Index(None, "actor_user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    # JSONB: event-specific details differ per event type (masked).
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    client_ip: Mapped[str | None] = mapped_column(INET)


class Alert(CreatedAtMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        check_in("channel", AlertChannel),
        Index(None, "alert_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(64))
    metric_value: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    threshold: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    message: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(16), server_default=AlertChannel.LOG.value)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
