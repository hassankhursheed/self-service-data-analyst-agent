"""Semantic catalog, metric definitions, business calendar and verified queries."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import SemanticObjectType, WeekStart
from app.db.models.base import Base, CreatedAtMixin, TimestampMixin, check_in


class SemanticCatalog(TimestampMixin, Base):
    __tablename__ = "semantic_catalog"
    __table_args__ = (
        UniqueConstraint("object_type", "object_name", "version"),
        check_in("object_type", SemanticObjectType),
        Index(
            "uq_semantic_catalog_active_object",
            "object_type",
            "object_name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(16))
    object_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    example_values: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    allowed_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    version: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())


class MetricDefinition(TimestampMixin, Base):
    __tablename__ = "metric_definitions"
    __table_args__ = (
        UniqueConstraint("name", "version"),
        Index(
            "uq_metric_definitions_active_name",
            "name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    definition_sql: Mapped[str] = mapped_column(Text)
    tables: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    join_condition: Mapped[str | None] = mapped_column(Text)
    synonyms: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    allowed_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    version: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class BusinessCalendarConfig(CreatedAtMixin, Base):
    __tablename__ = "business_calendar_config"
    __table_args__ = (
        check_in("week_start", WeekStart),
        CheckConstraint(
            "fiscal_year_start_month BETWEEN 1 AND 12", name="fiscal_year_start_month_range"
        ),
        Index(
            "uq_business_calendar_config_one_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    reference_date: Mapped[date] = mapped_column(Date)
    time_zone: Mapped[str] = mapped_column(String(64), server_default="UTC")
    fiscal_year_start_month: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    week_start: Mapped[str] = mapped_column(String(8), server_default=WeekStart.MONDAY.value)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=false())


class VerifiedQuery(TimestampMixin, Base):
    """Versioned verified examples; each correction is a new version in the same lineage."""

    __tablename__ = "verified_queries"
    __table_args__ = (
        UniqueConstraint("lineage_id", "version"),
        Index(
            "uq_verified_queries_active_lineage",
            "lineage_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index(None, "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    lineage_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    question_text: Mapped[str] = mapped_column(Text)
    sql_text: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    source_question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
