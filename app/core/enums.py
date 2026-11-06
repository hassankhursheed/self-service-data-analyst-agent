"""Allowed values shared across the application and enforced in the database.

Each enum here backs a CHECK constraint in the application schema, so the database and
the code agree on the allowed values.
"""

from enum import StrEnum


class RoleName(StrEnum):
    SALES_MANAGER = "sales_manager"
    FINANCE_ANALYST = "finance_analyst"
    OPERATIONS_MANAGER = "operations_manager"
    ADMIN = "admin"


class DbRole(StrEnum):
    """NOLOGIN PostgreSQL group roles the agent switches to (database-design.md)."""

    SALES_RO = "sales_ro"
    FINANCE_RO = "finance_ro"
    OPERATIONS_RO = "operations_ro"


class RegionCode(StrEnum):
    EUROPE = "EUROPE"
    AMERICAS = "AMERICAS"
    ROW = "ROW"


class QuestionStatus(StrEnum):
    """States from brief section 11 (see docs/design/langgraph-design.md)."""

    RECEIVED = "RECEIVED"
    GUARDRAIL_CHECKED = "GUARDRAIL_CHECKED"
    UNDERSTOOD = "UNDERSTOOD"
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED"
    SQL_GENERATED = "SQL_GENERATED"
    VALIDATED = "VALIDATED"
    EXECUTED = "EXECUTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    REPAIRING = "REPAIRING"
    ANSWERED = "ANSWERED"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


FINAL_STATUSES: tuple[QuestionStatus, ...] = (
    QuestionStatus.ANSWERED,
    QuestionStatus.BLOCKED,
    QuestionStatus.REJECTED,
    QuestionStatus.FAILED,
)


class NodeName(StrEnum):
    INTAKE = "N-01"
    GUARDRAILS = "N-02"
    INTENT = "N-03"
    CLARIFICATION = "N-04"
    CONTEXT = "N-05"
    SQL_GENERATION = "N-06"
    VALIDATION = "N-07"
    EXECUTION = "N-08"
    REPAIR = "N-09"
    ANSWER = "N-10"
    AUDIT = "N-11"


class QueryKind(StrEnum):
    INITIAL = "initial"
    REGENERATION = "regeneration"
    REPAIR = "repair"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExecutionStatus(StrEnum):
    SUCCESS = "success"
    DB_ERROR = "db_error"
    TIMEOUT = "timeout"


class BlockStage(StrEnum):
    INPUT_GUARDRAIL = "input_guardrail"
    CONTEXT = "context"
    SQL_VALIDATION = "sql_validation"


class Rating(StrEnum):
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"


class ReviewStatus(StrEnum):
    OPEN = "open"
    VERIFIED = "verified"
    CONVERTED = "converted"
    DISMISSED = "dismissed"


class SemanticObjectType(StrEnum):
    TABLE = "table"
    COLUMN = "column"
    JOIN = "join"
    SYNONYM = "synonym"


class WeekStart(StrEnum):
    MONDAY = "monday"
    SUNDAY = "sunday"


class CaseType(StrEnum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    HARD = "hard"
    AMBIGUOUS = "ambiguous"
    UNSAFE = "unsafe"
    ACCESS_CONTROL = "access_control"


class ExpectedBehaviour(StrEnum):
    CORRECT_RESULT = "correct_result"
    CLARIFY = "clarify"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    REGION_ONLY = "region_only"
    EMPTY_RESULT = "empty_result"


class EvalRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorStatus(StrEnum):
    OPEN = "open"
    RERUN = "rerun"
    RESOLVED = "resolved"


class AlertChannel(StrEnum):
    LOG = "log"
    EMAIL = "email"
    SLACK = "slack"
