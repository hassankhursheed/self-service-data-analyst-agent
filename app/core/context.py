"""The authenticated user's identity as passed to data access.

Built from the verified token and the database (a later step), never from question text.
"""

import uuid

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.enums import RegionCode, RoleName


class UserContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    username: str
    role: RoleName
    region: RegionCode | None = None
    user_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _region_matches_role(self) -> "UserContext":
        if self.role is RoleName.SALES_MANAGER and self.region is None:
            raise ValueError("a sales manager must have a region")
        if self.role is not RoleName.SALES_MANAGER and self.region is not None:
            raise ValueError("only sales managers have a region")
        return self
