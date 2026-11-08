"""IDs in the agent state are plain uuid.UUID values (checkpoints can restore them)."""

import uuid

from app.agent.state import AgentRequest
from app.core.ids import plain_uuid


class DriverUUID(uuid.UUID):
    """Stands in for asyncpg's own UUID subclass."""


def test_driver_uuids_become_plain_uuids() -> None:
    raw = DriverUUID("0b7d4c1a-6a8e-4c43-9f0f-2a1e5b8c9d10")
    assert type(plain_uuid(raw)) is uuid.UUID
    assert plain_uuid(raw) == raw
    request = AgentRequest(username="u", role=None, is_active=True, question="q", user_id=raw)
    assert type(request.user_id) is uuid.UUID
