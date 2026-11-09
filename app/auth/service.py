"""Login and token validation against the users, roles and regions tables."""

import asyncio
import datetime as dt
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuthenticatedUser, TokenResponse
from app.auth.tokens import InvalidToken, TokenService
from app.core.enums import RegionCode, RoleName
from app.core.errors import AppError
from app.core.security import hash_password, verify_password
from app.db.models import AuditLog, Role, User, UserRegion, UserRole

logger = logging.getLogger(__name__)

# Verified when the user does not exist, so a wrong username takes as long as a wrong
# password and timing does not reveal which usernames exist.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class InvalidCredentials(AppError):
    """Wrong username, wrong password or disabled account; the reason is not revealed."""

    code = "INVALID_CREDENTIALS"
    user_message = "The username or password is not correct."


async def load_user(session: AsyncSession, user_id: uuid.UUID) -> tuple[User, AuthenticatedUser]:
    """The user row plus role and region, always read fresh from the database."""
    user = await session.get(User, user_id)
    if user is None:
        raise InvalidToken("user no longer exists")
    role_name = await session.scalar(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    region_code = await session.scalar(
        select(UserRegion.region_code)
        .where(UserRegion.user_id == user.id)
        .order_by(UserRegion.region_code)
    )
    return user, AuthenticatedUser(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=RoleName(role_name) if role_name else None,
        region=RegionCode(region_code) if region_code else None,
        is_active=user.is_active,
    )


class AuthService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], tokens: TokenService) -> None:
        self.sessions = sessions
        self.tokens = tokens

    async def login(
        self, username: str, password: str, *, client_ip: str | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> TokenResponse:  # fmt: skip
        async with self.sessions() as session, session.begin():
            user = await session.scalar(select(User).where(User.username == username.strip()))
            # Argon2 is slow on purpose: run it off the event loop (Step 24).
            password_ok = await asyncio.to_thread(
                verify_password, user.password_hash if user else _DUMMY_HASH, password
            )
            if user is None or not password_ok or not user.is_active:
                reason = (
                    "unknown_user"
                    if user is None
                    else ("disabled" if password_ok else "wrong_password")
                )
                session.add(
                    AuditLog(
                        correlation_id=correlation_id,
                        actor_user_id=user.id if user else None,
                        event_type="login_failed",
                        target_type="user",
                        target_id=username.strip()[:64],
                        details={"reason": reason},
                        client_ip=client_ip,
                    )
                )
                await session.flush()
                failed = True
            else:
                failed = False
                _, identity = await load_user(session, user.id)
                user.last_login_at = dt.datetime.now(dt.UTC)
                session.add(
                    AuditLog(
                        correlation_id=correlation_id,
                        actor_user_id=user.id,
                        event_type="login",
                        target_type="user",
                        target_id=str(user.id),
                        details={"role": identity.role.value if identity.role else None},
                        client_ip=client_ip,
                    )
                )
                token = self.tokens.issue(user.id, user.token_version)
        if failed:
            raise InvalidCredentials("login failed")
        return TokenResponse(
            access_token=token,
            expires_in=self.tokens.config.access_token_minutes * 60,
            user=identity,
        )

    async def record_rejected_token(
        self,
        reason: str,
        path: str,
        *,
        correlation_id: uuid.UUID | None = None,
        client_ip: str | None = None,
    ) -> None:
        """Audit a refused token (brief scenario 2 and 26). Never raises: the 401 stands."""
        try:
            async with self.sessions() as session, session.begin():
                session.add(
                    AuditLog(
                        correlation_id=correlation_id,
                        event_type="token_rejected",
                        target_type="endpoint",
                        target_id=path[:64],
                        details={"reason": reason},
                        client_ip=client_ip,
                    )
                )
        except Exception:  # the refusal must not turn into a 500
            logger.warning("could not audit a rejected token", exc_info=True)

    async def authenticate(self, token: str) -> AuthenticatedUser:
        """Validate a bearer token and load the caller's current role and region."""
        claims = self.tokens.decode(token)
        async with self.sessions() as session:
            user, identity = await load_user(session, claims.user_id)
        if not user.is_active:
            raise InvalidToken("account disabled")
        if user.token_version != claims.token_version:
            raise InvalidToken("token revoked")
        return identity
