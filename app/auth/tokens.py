"""JWT access tokens: user ID and token version only; role and region stay in the database."""

import datetime as dt
import uuid

import jwt

from app.auth.models import TokenClaims
from app.core.config import AuthConfig
from app.core.errors import AppError

MIN_PRODUCTION_SECRET = 32


class InvalidToken(AppError):
    """Missing, malformed, tampered, expired or revoked token (HTTP 401)."""

    code = "INVALID_TOKEN"
    user_message = "Your session is not valid. Please log in again."


class TokenExpired(InvalidToken):
    code = "TOKEN_EXPIRED"
    user_message = "Your session has expired. Please log in again."


class TokenService:
    def __init__(self, secret: str, config: AuthConfig, *, production: bool = False) -> None:
        if not secret or (production and len(secret) < MIN_PRODUCTION_SECRET):
            raise ValueError(f"JWT_SECRET_KEY must be at least {MIN_PRODUCTION_SECRET} characters")
        self._secret = secret
        self.config = config

    def issue(
        self, user_id: uuid.UUID, token_version: int, *, now: dt.datetime | None = None
    ) -> str:
        now = now or dt.datetime.now(dt.UTC)
        payload = {
            "sub": str(user_id),
            "ver": token_version,
            "iss": self.config.issuer,
            "iat": int(now.timestamp()),
            "exp": int((now + dt.timedelta(minutes=self.config.access_token_minutes)).timestamp()),
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(payload, self._secret, algorithm=self.config.jwt_algorithm)

    def decode(self, token: str) -> TokenClaims:
        """Verify signature, algorithm, issuer and expiry; raise InvalidToken otherwise."""
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self.config.jwt_algorithm],
                issuer=self.config.issuer,
                options={"require": ["sub", "ver", "exp", "iat", "iss", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpired("token expired") from exc
        except jwt.PyJWTError as exc:
            raise InvalidToken(f"invalid token: {type(exc).__name__}") from exc
        try:
            return TokenClaims(
                user_id=uuid.UUID(str(payload["sub"])),
                token_version=int(payload["ver"]),
                issued_at=dt.datetime.fromtimestamp(int(payload["iat"]), dt.UTC),
                expires_at=dt.datetime.fromtimestamp(int(payload["exp"]), dt.UTC),
                token_id=str(payload["jti"]),
            )
        except (ValueError, TypeError) as exc:
            raise InvalidToken("malformed token claims") from exc
