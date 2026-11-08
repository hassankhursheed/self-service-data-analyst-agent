"""IDs that are always plain ``uuid.UUID`` values.

asyncpg returns its own UUID subclass, which Pydantic keeps as it is. LangGraph's
checkpoint serializer refuses to restore that type (found by the Step 26 load test:
"Blocked deserialization of asyncpg.pgproto.pgproto.UUID"), so IDs that reach the agent
state are converted to the standard type.
"""

import uuid
from typing import Annotated

from pydantic import AfterValidator


def plain_uuid(value: uuid.UUID) -> uuid.UUID:
    return value if type(value) is uuid.UUID else uuid.UUID(int=value.int)


PlainUUID = Annotated[uuid.UUID, AfterValidator(plain_uuid)]
