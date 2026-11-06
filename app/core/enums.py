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


class BlockReason(StrEnum):
    """Why a question or query was blocked (stored in blocked_queries, shown on the dashboard)."""

    QUESTION_EMPTY = "QUESTION_EMPTY"
    QUESTION_TOO_LONG = "QUESTION_TOO_LONG"
    USER_DISABLED = "USER_DISABLED"
    NO_ROLE = "NO_ROLE"
    ADMIN_NO_BUSINESS_DATA = "ADMIN_NO_BUSINESS_DATA"
    OFF_TOPIC = "OFF_TOPIC"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    WRITE_REQUEST = "WRITE_REQUEST"
    PERSONAL_DATA_REQUEST = "PERSONAL_DATA_REQUEST"
    NO_DATA_ACCESS = "NO_DATA_ACCESS"
    NO_ALLOWED_DATA = "NO_ALLOWED_DATA"
    DATABASE_REFUSED = "DATABASE_REFUSED"
    EMPTY_SQL = "EMPTY_SQL"
    PARSE_ERROR = "PARSE_ERROR"
    MULTIPLE_STATEMENTS = "MULTIPLE_STATEMENTS"
    NOT_SELECT = "NOT_SELECT"
    WRITE_STATEMENT = "WRITE_STATEMENT"
    DDL_STATEMENT = "DDL_STATEMENT"
    PERMISSION_STATEMENT = "PERMISSION_STATEMENT"
    SET_STATEMENT = "SET_STATEMENT"
    COPY_STATEMENT = "COPY_STATEMENT"
    PROCEDURE_CALL = "PROCEDURE_CALL"
    SELECT_INTO = "SELECT_INTO"
    LOCKING_CLAUSE = "LOCKING_CLAUSE"
    SYSTEM_CATALOG = "SYSTEM_CATALOG"
    SCHEMA_QUALIFIED = "SCHEMA_QUALIFIED"
    FORBIDDEN_FUNCTION = "FORBIDDEN_FUNCTION"
    REAL_DATE_FUNCTION = "REAL_DATE_FUNCTION"
    TABLE_NOT_ALLOWED = "TABLE_NOT_ALLOWED"
    COLUMN_NOT_ALLOWED = "COLUMN_NOT_ALLOWED"
    INVALID_LIMIT = "INVALID_LIMIT"


class AlertChannel(StrEnum):
    LOG = "log"
    EMAIL = "email"
    SLACK = "slack"
