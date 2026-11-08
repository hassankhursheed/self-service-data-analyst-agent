"""Admin user management: create, disable/enable, reset password, assign role and regions.

Every action requires an admin, is validated, and is written to the audit log. Disabling
a user or resetting a password bumps ``token_version`` so existing tokens stop working.
"""

import asyncio
import datetime as dt
import re
import uuid

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuthenticatedUser
from app.auth.service import load_user
from app.core.config import AuthConfig
from app.core.enums import RegionCode, RoleName
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.models import AuditLog, Role, User, UserRegion, UserRole

USERNAME = re.compile(r"^[a-z][a-z0-9._-]{2,63}$")


class UserAdminError(AppError):
    code = "USER_ADMIN_ERROR"
    user_message = "The user could not be changed."


class NotAllowed(AppError):
    code = "ADMIN_ONLY"
    user_message = "Only administrators can manage users."


class UserNotFound(AppError):
    code = "NOT_FOUND"
    user_message = "User not found."


class UsernameTaken(UserAdminError):
    code = "USERNAME_TAKEN"
    user_message = "That username is already taken."


class InvalidUserInput(UserAdminError):
    code = "VALIDATION_ERROR"


class UserView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    username: str
    display_name: str
    role: RoleName | None
    region: RegionCode | None
    is_active: bool
    last_login_at: dt.datetime | None


def check_role_and_region(role: RoleName | None, region: RegionCode | None) -> None:
    if role is RoleName.SALES_MANAGER and region is None:
        raise InvalidUserInput(
            "sales manager without region", user_message="A sales manager needs a region."
        )
    if role is not RoleName.SALES_MANAGER and region is not None:
        raise InvalidUserInput(
            "region for non-sales role", user_message="Only sales managers have a region."
        )


class UserAdminService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], auth: AuthConfig) -> None:
        self.sessions = sessions
        self.auth = auth

    # --- helpers --------------------------------------------------------------------------

    @staticmethod
    def _require_admin(actor: AuthenticatedUser) -> None:
        if not actor.is_admin or not actor.is_active:
            raise NotAllowed(f"{actor.username} is not an admin")

    def _check_password(self, password: str) -> None:
        if len(password) < self.auth.min_password_length:
            raise InvalidUserInput(
                "password too short",
                user_message=f"The password must have at least {self.auth.min_password_length} characters.",  # noqa: E501
            )

    @staticmethod
    def _audit(session: AsyncSession, actor: AuthenticatedUser, event: str, target: uuid.UUID,
               details: dict[str, object], correlation_id: uuid.UUID | None) -> None:  # fmt: skip
        session.add(
            AuditLog(
                correlation_id=correlation_id,
                actor_user_id=actor.user_id,
                event_type=event,
                target_type="user",
                target_id=str(target),
                details=details,
            )
        )

    async def _set_role_and_region(
        self, session: AsyncSession, user_id: uuid.UUID, role: RoleName | None,
        region: RegionCode | None, actor: AuthenticatedUser,
    ) -> None:  # fmt: skip
        await session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        await session.execute(delete(UserRegion).where(UserRegion.user_id == user_id))
        if role is not None:
            role_id = await session.scalar(select(Role.id).where(Role.name == role.value))
            if role_id is None:
                raise InvalidUserInput(
                    f"unknown role {role}", user_message="That role does not exist."
                )
            session.add(UserRole(user_id=user_id, role_id=role_id, assigned_by=actor.user_id))
        if region is not None:
            session.add(
                UserRegion(user_id=user_id, region_code=region.value, assigned_by=actor.user_id)
            )

    async def _view(self, session: AsyncSession, user_id: uuid.UUID) -> UserView:
        user, identity = await load_user(session, user_id)
        return UserView(
            id=user.id, username=user.username, display_name=user.display_name,
            role=identity.role, region=identity.region, is_active=user.is_active,
            last_login_at=user.last_login_at,
        )  # fmt: skip

    async def _get(self, session: AsyncSession, user_id: uuid.UUID) -> User:
        user = await session.get(User, user_id)
        if user is None:
            raise UserNotFound(f"user {user_id} not found")
        return user

    # --- actions --------------------------------------------------------------------------

    async def list_users(self, actor: AuthenticatedUser) -> list[UserView]:
        self._require_admin(actor)
        async with self.sessions() as session:
            ids = list(await session.scalars(select(User.id).order_by(User.username)))
            return [await self._view(session, user_id) for user_id in ids]

    async def create_user(
        self, actor: AuthenticatedUser, *, username: str, display_name: str, password: str,
        role: RoleName | None, region: RegionCode | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> UserView:  # fmt: skip
        self._require_admin(actor)
        username = username.strip().lower()
        if not USERNAME.match(username):
            raise InvalidUserInput(
                "bad username",
                user_message="Use 3-64 lower-case letters, digits, dots, dashes or underscores.",
            )
        self._check_password(password)
        check_role_and_region(role, region)
        async with self.sessions() as session, session.begin():
            if await session.scalar(select(User.id).where(User.username == username)):
                raise UsernameTaken(username)
            user = User(username=username, display_name=display_name.strip() or username,
                        password_hash=await asyncio.to_thread(hash_password, password))  # fmt: skip
            session.add(user)
            await session.flush()
            await self._set_role_and_region(session, user.id, role, region, actor)
            self._audit(session, actor, "user_created", user.id,
                        {"username": username, "role": role.value if role else None,
                         "region": region.value if region else None}, correlation_id)  # fmt: skip
            await session.flush()
            return await self._view(session, user.id)

    async def set_active(
        self, actor: AuthenticatedUser, user_id: uuid.UUID, active: bool,
        correlation_id: uuid.UUID | None = None,
    ) -> UserView:  # fmt: skip
        self._require_admin(actor)
        if user_id == actor.user_id and not active:
            raise InvalidUserInput(
                "self-disable", user_message="You cannot disable your own account."
            )
        async with self.sessions() as session, session.begin():
            user = await self._get(session, user_id)
            if user.is_active and not active:
                user.token_version += 1  # existing tokens stop working at once
            user.is_active = active
            self._audit(session, actor, "user_enabled" if active else "user_disabled", user.id,
                        {"username": user.username}, correlation_id)  # fmt: skip
            await session.flush()
            return await self._view(session, user.id)

    async def reset_password(
        self, actor: AuthenticatedUser, user_id: uuid.UUID, new_password: str,
        correlation_id: uuid.UUID | None = None,
    ) -> UserView:  # fmt: skip
        self._require_admin(actor)
        self._check_password(new_password)
        async with self.sessions() as session, session.begin():
            user = await self._get(session, user_id)
            user.password_hash = await asyncio.to_thread(hash_password, new_password)
            user.token_version += 1
            self._audit(session, actor, "password_reset", user.id, {"username": user.username},
                        correlation_id)  # fmt: skip
            await session.flush()
            return await self._view(session, user.id)

    async def assign_role(
        self, actor: AuthenticatedUser, user_id: uuid.UUID, role: RoleName | None,
        region: RegionCode | None = None, correlation_id: uuid.UUID | None = None,
    ) -> UserView:  # fmt: skip
        self._require_admin(actor)
        check_role_and_region(role, region)
        async with self.sessions() as session, session.begin():
            user = await self._get(session, user_id)
            await self._set_role_and_region(session, user.id, role, region, actor)
            self._audit(session, actor, "role_assigned", user.id,
                        {"username": user.username, "role": role.value if role else None,
                         "region": region.value if region else None}, correlation_id)  # fmt: skip
            await session.flush()
            return await self._view(session, user.id)
