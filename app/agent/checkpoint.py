"""Checkpoint serializer that only restores the application's own state types.

LangGraph deserialises checkpoints with msgpack. Unregistered classes trigger warnings and
will be refused in future versions, so the allow-list is built from the ``AgentState``
type tree: every Pydantic model and enum from ``app.*`` reachable from its fields.
"""

from enum import Enum
from typing import Any, get_args

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

from app.agent.state import AgentState


def _collect(tp: Any, found: set[type], seen: set[int]) -> None:  # noqa: ANN401
    if id(tp) in seen:
        return
    seen.add(id(tp))
    for arg in get_args(tp):
        _collect(arg, found, seen)
    if not isinstance(tp, type) or not tp.__module__.startswith("app."):
        return
    if issubclass(tp, Enum):
        found.add(tp)
    elif issubclass(tp, BaseModel):
        found.add(tp)
        for field in tp.model_fields.values():
            _collect(field.annotation, found, seen)


def state_types() -> list[tuple[str, str]]:
    """(module, class name) for every app type that can appear in a checkpoint."""
    found: set[type] = set()
    _collect(AgentState, found, set())
    return sorted((t.__module__, t.__qualname__) for t in found)


def checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=state_types())
