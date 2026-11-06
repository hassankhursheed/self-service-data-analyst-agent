"""Users, roles and region assignments."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DbRole, RegionCode, RoleName
from app.db.models.base import Base, CreatedAtMixin, TimestampMixin, check_in


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    # Bumped on disable or password reset so existing tokens stop working.
    token_version: Mapped[int] = mapped_column(Integer, server_default="0")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(CreatedAtMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        check_in("name", RoleName),
        check_in("db_role", DbRole, nullable=True),
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    # PostgreSQL group role used by the agent; NULL for admin (no business data).
    db_role: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, server_default="")


class UserRole(CreatedAtMixin, Base):
    """One role per user: the primary key is the user id."""

    __tablename__ = "user_roles"
    __table_args__ = (Index(None, "role_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"))
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class UserRegion(CreatedAtMixin, Base):
    __tablename__ = "user_regions"
    __table_args__ = (check_in("region_code", RegionCode),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    region_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
