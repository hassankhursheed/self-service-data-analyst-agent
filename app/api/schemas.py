"""Request and response models of the HTTP API (docs/design/api-design.md).

Every response body carries ``correlation_id`` (the same value as the ``X-Correlation-ID``
header). Models for endpoints that are built in later steps (metrics, verified queries,
evaluation) are defined here already, so the OpenAPI contract is complete.
"""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.conversations import ConversationSummary, QuestionSummary
from app.agent.response import AgentResponse, TablePage
from app.auth.models import AuthenticatedUser
from app.core.enums import (
    CaseType,
    ErrorStatus,
    EvalRunStatus,
    ExpectedBehaviour,
    QuestionStatus,
    Rating,
    RegionCode,
    RoleName,
)
from app.services.users import UserView
from app.services.verified_library import LibraryItem, ReviewItem

MAX_QUESTION_CHARS = 4000  # hard cap on the body; the guardrail applies the real limit
MAX_COMMENT_CHARS = 1000


class ApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Envelope(BaseModel):
    correlation_id: uuid.UUID


class Page(Envelope):
    total: int
    page: int
    page_size: int


# --- auth and health -------------------------------------------------------------------


class LoginRequest(ApiRequest):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(Envelope):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (OAuth token type)
    expires_in: int
    user: AuthenticatedUser


class MeResponse(Envelope):
    user: AuthenticatedUser


class HealthResponse(Envelope):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "down"]
    version: str


# --- questions -------------------------------------------------------------------------


class AskRequest(ApiRequest):
    question: str = Field(max_length=MAX_QUESTION_CHARS)
    conversation_id: uuid.UUID | None = None


class ClarifyRequest(ApiRequest):
    conversation_id: uuid.UUID
    answer: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class AskResponse(AgentResponse):
    conversation_id: uuid.UUID
    question_id: uuid.UUID | None


class ConversationList(Page):
    items: list[ConversationSummary]


class ConversationDetailResponse(Envelope):
    id: uuid.UUID
    title: str
    questions: list[QuestionSummary]
    # Full response of the latest question (the checkpointer keeps only the latest state).
    latest: AgentResponse | None


class TablePageResponse(Envelope):
    table: TablePage | None


class FeedbackRequest(ApiRequest):
    question_id: uuid.UUID
    rating: Rating
    comment: str | None = Field(default=None, max_length=MAX_COMMENT_CHARS)


class FeedbackResponse(Envelope):
    feedback_id: int
    rating: Rating


# --- admin: review ---------------------------------------------------------------------


class BlockedItem(BaseModel):
    id: int
    correlation_id: uuid.UUID
    username: str | None
    role: str | None
    question: str | None
    stage: str
    reason_code: str
    reason_text: str
    sql_text: str | None
    created_at: dt.datetime


class BlockedList(Page):
    items: list[BlockedItem]


class ErrorItem(BaseModel):
    id: int
    correlation_id: uuid.UUID
    question_id: uuid.UUID | None
    username: str | None
    node_name: str | None
    error_type: str
    retryable: bool
    error_message: str
    status: ErrorStatus
    created_at: dt.datetime


class ErrorList(Page):
    items: list[ErrorItem]


class RerunResponse(Envelope):
    error_id: int
    new_question_id: uuid.UUID | None
    conversation_id: uuid.UUID
    status: QuestionStatus | None


# --- admin: users ----------------------------------------------------------------------


class CreateUserRequest(ApiRequest):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(default="", max_length=128)
    password: str = Field(min_length=1, max_length=256)
    role: RoleName | None = None
    region: RegionCode | None = None


class UpdateUserRequest(ApiRequest):
    """Only the fields sent are changed. ``role`` and ``region`` are set together."""

    is_active: bool | None = None
    role: RoleName | None = None
    region: RegionCode | None = None


class ResetPasswordRequest(ApiRequest):
    new_password: str = Field(min_length=1, max_length=256)


class UserResponse(Envelope, UserView):
    pass


class UserList(Page):
    items: list[UserView]


# --- admin: later steps (501 for now, final models) ------------------------------------


class OutcomeCounts(BaseModel):
    answered: int
    blocked: int
    rejected: int
    failed: int


class FeedbackCounts(BaseModel):
    helpful: int
    not_helpful: int


class MetricsResponse(Envelope):
    questions_today: int
    questions_by_role: dict[str, int]
    outcomes: OutcomeCounts
    blocked_by_reason: dict[str, int]
    repair_attempts: int
    repair_success_rate: float | None
    clarifications_asked: int
    latency_avg_ms: float | None
    latency_p95_ms: float | None
    tokens_today: int
    cost_today_usd: Decimal
    feedback: FeedbackCounts
    latest_eval_run: uuid.UUID | None
    failed_logins: int


class VerifiedQueryList(Page):
    items: list[LibraryItem]


class ReviewList(Page):
    """Not-helpful answers, blocked queries and failures in one list (brief §16)."""

    items: list[ReviewItem]


class VerifyRequest(ApiRequest):
    """Mark a question and its SQL as verified, or correct it (``lineage_id`` = new version).
    The SQL must pass the validator for every allowed role."""

    source_question_id: uuid.UUID | None = None
    question_text: str = Field(min_length=3, max_length=MAX_QUESTION_CHARS)
    sql_text: str = Field(min_length=10, max_length=20_000)
    description: str = Field(min_length=3, max_length=1000)
    allowed_roles: list[RoleName] = Field(min_length=1)
    metrics_used: list[str] = []
    lineage_id: uuid.UUID | None = None


class UpdateVerifiedRequest(ApiRequest):
    is_active: bool


class VerifiedQueryResponse(Envelope, LibraryItem):
    pass


class EvalCaseResponse(Envelope):
    case_id: int
    case_key: str
    dataset: str


class EvalRunRequest(ApiRequest):
    dataset: str = Field(min_length=1)
    dataset_version: int | None = None
    experiment_name: str = Field(min_length=1, max_length=100)
    verified_examples_enabled: bool = True
    subset: list[str] | None = None
    case_types: list[CaseType] | None = None


class EvalRunStarted(Envelope):
    run_id: uuid.UUID
    status: EvalRunStatus


class EvalRunItem(BaseModel):
    run_id: uuid.UUID
    experiment_name: str
    model_name: str
    status: EvalRunStatus
    execution_accuracy: Decimal | None
    clarification_rate: Decimal | None
    unsafe_blocked_rate: Decimal | None
    access_leaks: int | None
    ungrounded_answers: int | None
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    avg_cost_usd: Decimal | None
    started_at: dt.datetime
    finished_at: dt.datetime | None


class EvalRunList(Page):
    items: list[EvalRunItem]


class EvalCaseRequest(ApiRequest):
    case_type: CaseType
    expected_behaviour: ExpectedBehaviour
    expected_sql: str | None = None
