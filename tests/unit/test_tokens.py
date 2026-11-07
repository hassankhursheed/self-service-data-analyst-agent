"""Step 17 unit tests: JWT access tokens (no database)."""

import datetime as dt
import uuid

import jwt
import pytest

from app.auth.tokens import InvalidToken, TokenExpired, TokenService
from app.core.config import AuthConfig

CONFIG = AuthConfig(
    jwt_algorithm="HS256", access_token_minutes=60, issuer="test-issuer", min_password_length=10
)
SECRET = "unit-test-secret-that-is-long-enough-123"
SERVICE = TokenService(SECRET, CONFIG)
USER = uuid.uuid4()


def test_issued_token_decodes_to_user_and_version() -> None:
    claims = SERVICE.decode(SERVICE.issue(USER, 3))
    assert (claims.user_id, claims.token_version) == (USER, 3)
    assert claims.expires_at - claims.issued_at == dt.timedelta(minutes=60)


def test_token_carries_no_role_or_region() -> None:
    payload = jwt.decode(SERVICE.issue(USER, 0), SECRET, algorithms=["HS256"], issuer="test-issuer")
    assert set(payload) == {"sub", "ver", "iss", "iat", "exp", "jti"}


def test_expired_token_is_refused() -> None:
    old = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    with pytest.raises(TokenExpired):
        SERVICE.decode(SERVICE.issue(USER, 0, now=old))


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-jwt",
        "a.b.c",
        TokenService("another-secret-that-is-long-enough-456", CONFIG).issue(USER, 0),
    ],
)
def test_invalid_or_foreign_tokens_are_refused(token: str) -> None:
    with pytest.raises(InvalidToken):
        SERVICE.decode(token)


def test_tampered_token_is_refused() -> None:
    header, _payload, signature = SERVICE.issue(USER, 0).split(".")
    forged = jwt.encode({"sub": str(uuid.uuid4()), "ver": 0}, "x" * 40, algorithm="HS256").split(
        "."
    )[1]
    with pytest.raises(InvalidToken):
        SERVICE.decode(f"{header}.{forged}.{signature}")


def test_unsigned_none_algorithm_is_refused() -> None:
    now = int(dt.datetime.now(dt.UTC).timestamp())
    unsigned = jwt.encode(
        {"sub": str(USER), "ver": 0, "iss": "test-issuer", "iat": now, "exp": now + 60, "jti": "x"},
        key=None,
        algorithm="none",
    )
    with pytest.raises(InvalidToken):
        SERVICE.decode(unsigned)


def test_wrong_issuer_is_refused() -> None:
    other = TokenService(SECRET, CONFIG.model_copy(update={"issuer": "someone-else"}))
    with pytest.raises(InvalidToken):
        SERVICE.decode(other.issue(USER, 0))


def test_missing_claims_are_refused() -> None:
    now = int(dt.datetime.now(dt.UTC).timestamp())
    token = jwt.encode({"sub": str(USER), "exp": now + 60}, SECRET, algorithm="HS256")
    with pytest.raises(InvalidToken):
        SERVICE.decode(token)


def test_short_secret_is_refused_in_production() -> None:
    with pytest.raises(ValueError, match="at least"):
        TokenService("short", CONFIG, production=True)
    TokenService("short-but-fine-in-development", CONFIG)
