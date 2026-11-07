"""Identity models shared by auth, the API and the agent."""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict

from app.core.enums import RegionCode, RoleName


class AuthenticatedUser(BaseModel):
    """The verified caller: user ID from the token, role and region from the database.

    Never built from question text.
    """

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    username: str
    role: RoleName | None
    region: RegionCode | None = None
    is_active: bool = True
    display_name: str = ""

    @property
    def is_admin(self) -> bool:
        return self.role is RoleName.ADMIN


class TokenClaims(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    token_version: int
    issued_at: dt.datetime
    expires_at: dt.datetime
    token_id: str


class TokenResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str
    token_type: str = "bearer"  # noqa: S105 (OAuth token type, not a secret)
    expires_in: int
    user: AuthenticatedUser
