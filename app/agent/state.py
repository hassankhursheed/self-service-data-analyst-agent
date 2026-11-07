"""Agent state: everything one question carries through the graph (langgraph-design.md).

Later nodes fill the typed slots; ``steps`` grows by one record per node, ready for the
audit trail written by N-11.
"""

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.charts import ChartSpec
from app.agent.intent import ClarificationDraft, IntentAnalysis
from app.agent.sql_output import GeneratedSQL
from app.core.context import UserContext
from app.core.enums import (
    BlockReason,
    BlockStage,
    Confidence,
    ExecutionStatus,
    NodeName,
    QueryKind,
    QuestionStatus,
    RegionCode,
    RoleName,
)
from app.db.analytics import QueryResult
from app.safety.guardrails import GuardrailResult
from app.safety.sql_validator import SqlValidationResult
from app.semantic.calendar import DateRange
from app.semantic.models import SemanticLayer
from app.semantic.retriever import RetrievedContext
from app.semantic.verified import VerifiedExample


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


class ConversationTurn(_Frozen):
    """What a follow-up may build on: an earlier question and how it was answered."""

    question: str
    interpreted_question: str
    status: QuestionStatus | None
    sql: str | None = None
    date_range_label: str | None = None


class ClarificationRecord(_Frozen):
    """One clarifying question and the user's reply (for the clarifications table)."""

    round: int
    question: str
    options: list[str]
    missing_parts: list[str]
    asked_at: dt.datetime
    answer: str | None = None
    answered_at: dt.datetime | None = None


class SqlAttempt(_Frozen):
    """One SQL the LLM produced (for generated_queries)."""

    attempt: int
    kind: QueryKind
    sql: str
    tables_used: list[str]
    metrics_used: list[str]
    confidence: Confidence
    verified_examples: list[str] = []


class ExecutionRecord(_Frozen):
    """One execution of validated SQL (for query_executions)."""

    attempt: int
    status: ExecutionStatus
    view_schema: str | None
    region: RegionCode | None
    row_count: int | None = None
    result_bytes: int | None = None
    latency_ms: int
    error: str | None = None


class BlockedQueryRecord(_Frozen):
    """A refusal, ready for the blocked_queries table (Step 16)."""

    stage: BlockStage
    reason_code: BlockReason
    reason_text: str
    sql: str | None = None
    detail: str | None = None


class Answer(_Frozen):
    """What N-10 produced: explanation, SQL description and chart."""

    text: str
    sql_description: str
    chart: ChartSpec
    grounded: bool
    source: Literal["llm", "template", "empty"]
    low_confidence_label: str | None = None
    confidence: Confidence = Confidence.MEDIUM


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
    intent: IntentAnalysis | None = None
    pending_clarification: ClarificationDraft | None = None
    clarifications: list[ClarificationRecord] = []
    assumptions: list[str] = []
    top_n: int | None = None
    date_range: DateRange | None = None
    semantic: SemanticLayer | None = None
    context: RetrievedContext | None = None
    # Verified examples chosen by N-05 and shown to N-06 as few-shot guidance (Step 20).
    verified_examples: list[VerifiedExample] = []
    generated: GeneratedSQL | None = None
    regeneration_attempts: int = 0
    validation: SqlValidationResult | None = None
    execution: QueryResult | None = None
    executed_sql: str | None = None
    last_db_error: str | None = None
    low_confidence: bool = False
    blocked: BlockedQueryRecord | None = None
    sql_attempts: list[SqlAttempt] = []
    executions: list[ExecutionRecord] = []
    # False when N-11 could not write the audit trail (the answer is still returned).
    audit_ok: bool | None = None
    repair_attempts: int = 0
    answer: Answer | None = None
    user_message: str | None = None
    # Why the question was REJECTED or BLOCKED (stored in blocked_queries / audit later).
    block_reason: BlockReason | None = None
    error: AgentErrorInfo | None = None
    usage: Usage = Usage()
    # One record per node of this question. A plain list (no reducer) so a new question in
    # the same conversation thread starts with an empty list.
    steps: list[StepRecord] = Field(default_factory=list)
    # Earlier questions in this conversation (for follow-ups), newest last.
    history: list[ConversationTurn] = []
    # The standalone question N-03 rewrote a follow-up into, shown as "Interpreted as".
    interpreted_question: str | None = None
    graph_version: str = ""
    prompt_versions: dict[str, str] = {}
    finished: bool = False
    thread_id: str | None = None
    # True while the graph is paused waiting for the user's clarification reply.
    awaiting_reply: bool = False
