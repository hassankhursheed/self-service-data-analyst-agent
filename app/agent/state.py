"""Agent state: everything one question carries through the graph (langgraph-design.md).

Later nodes fill the typed slots; ``steps`` grows by one record per node (LangGraph
reducer), ready for the audit trail.
"""

import datetime as dt
import operator
import uuid
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.context import UserContext
from app.core.enums import BlockReason, Confidence, NodeName, QuestionStatus, RegionCode, RoleName
from app.db.analytics import QueryResult
from app.safety.guardrails import GuardrailResult
from app.safety.sql_validator import SqlValidationResult
from app.semantic.calendar import DateRange
from app.semantic.retriever import RetrievedContext


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class AgentRequest(_Frozen):
    """What the API hands to the graph. Identity comes from the verified token and the
    database, never from the question text."""

    username: str
    role: RoleName | None
    region: RegionCode | None = None
    is_active: bool
    question: str
    user_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None


class StepRecord(_Frozen):
    node: NodeName
    from_status: QuestionStatus | None
    to_status: QuestionStatus | None
    started_at: dt.datetime
    ended_at: dt.datetime
    duration_ms: float
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    error_code: str | None = None


class Intent(_Frozen):
    summary: str
    metrics: list[str] = []
    time_phrase: str | None = None


class GeneratedSQL(_Frozen):
    sql: str
    tables_used: list[str] = []
    metrics_used: list[str] = []
    assumptions: list[str] = []
    confidence: Confidence = Confidence.LOW


class Answer(_Frozen):
    text: str
    confidence: Confidence = Confidence.LOW


class AgentErrorInfo(_Frozen):
    node: NodeName
    code: str
    detail: str
    retryable: bool = False


class Usage(_Frozen):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class AgentState(BaseModel):
    request: AgentRequest
    correlation_id: uuid.UUID | None = None
    user: UserContext | None = None
    status: QuestionStatus | None = None
    question: str = ""
    guardrail: GuardrailResult | None = None
    notices: list[str] = []
    intent: Intent | None = None
    date_range: DateRange | None = None
    context: RetrievedContext | None = None
    generated: GeneratedSQL | None = None
    regeneration_attempts: int = 0
    validation: SqlValidationResult | None = None
    execution: QueryResult | None = None
    repair_attempts: int = 0
    answer: Answer | None = None
    user_message: str | None = None
    # Why the question was REJECTED or BLOCKED (stored in blocked_queries / audit later).
    block_reason: BlockReason | None = None
    error: AgentErrorInfo | None = None
    usage: Usage = Usage()
    steps: Annotated[list[StepRecord], operator.add] = Field(default_factory=list)
    graph_version: str = ""
    prompt_versions: dict[str, str] = {}
    finished: bool = False
