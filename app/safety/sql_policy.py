"""SQL safety policy loaded from config/sql_policy.yaml, plus user-facing block messages."""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import PROJECT_ROOT
from app.core.enums import BlockReason
from app.core.yaml_config import load_yaml_model

SQL_POLICY_FILE = PROJECT_ROOT / "config" / "sql_policy.yaml"


class SqlPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    max_question_length: int = Field(gt=0)
    default_limit: int = Field(gt=0)
    max_limit: int = Field(gt=0)
    allowed_functions: frozenset[str]
    allowed_anonymous_functions: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def _limits(self) -> "SqlPolicy":
        if self.default_limit > self.max_limit:
            raise ValueError("default_limit must not exceed max_limit")
        return self


def load_sql_policy(path: Path = SQL_POLICY_FILE) -> SqlPolicy:
    return load_yaml_model(path, SqlPolicy)


@lru_cache
def get_sql_policy() -> SqlPolicy:
    return load_sql_policy()


# Plain-language reasons shown to the user (one per code).
BLOCK_MESSAGES: dict[BlockReason, str] = {
    BlockReason.QUESTION_EMPTY: "Please type a question.",
    BlockReason.QUESTION_TOO_LONG: "Your question is too long. Please shorten it.",
    BlockReason.USER_DISABLED: "Your account is disabled. Please contact the data owner.",
    BlockReason.NO_ROLE: (
        "Your account has no role yet, so it cannot ask business questions. "
        "Please contact the data owner."
    ),
    BlockReason.ADMIN_NO_BUSINESS_DATA: (
        "Admin accounts manage the system and do not ask business questions. "
        "Please use a business account."
    ),
    BlockReason.OFF_TOPIC: (
        "Sorry, I can only help with questions about Northwind's sales, customers, "
        "products and shipping."
    ),
    BlockReason.PROMPT_INJECTION: (
        "I can't change how I work or share my instructions. "
        "Please ask a question about Northwind's data."
    ),
    BlockReason.WRITE_REQUEST: "I can only read data, so I can't change, add or delete anything.",
    BlockReason.PERSONAL_DATA_REQUEST: "That personal information is not available to your role.",
    BlockReason.NO_DATA_ACCESS: "Your account has no access to business data.",
    BlockReason.NO_ALLOWED_DATA: (
        "I could not find data your role may use to answer this question."
    ),
    BlockReason.DATABASE_REFUSED: (
        "The database refused this query for your role, so it was not run."
    ),
    BlockReason.EMPTY_SQL: "No query was produced for this question.",
    BlockReason.PARSE_ERROR: "The generated query could not be read, so it was not run.",
    BlockReason.MULTIPLE_STATEMENTS: "Only one query can run at a time.",
    BlockReason.NOT_SELECT: "Only questions that read data are allowed.",
    BlockReason.WRITE_STATEMENT: (
        "Changing or deleting data is not allowed. This assistant only reads data."
    ),
    BlockReason.DDL_STATEMENT: "Creating, changing or removing tables is not allowed.",
    BlockReason.PERMISSION_STATEMENT: "Changing access rights is not allowed.",
    BlockReason.SET_STATEMENT: "Changing session settings is not allowed.",
    BlockReason.COPY_STATEMENT: "Copying data to or from files is not allowed.",
    BlockReason.PROCEDURE_CALL: "Running procedures or code blocks is not allowed.",
    BlockReason.SELECT_INTO: "Saving results into a new table is not allowed.",
    BlockReason.LOCKING_CLAUSE: "Locking rows is not allowed.",
    BlockReason.SYSTEM_CATALOG: "Database system tables are not available.",
    BlockReason.SCHEMA_QUALIFIED: "Tables must be used by their plain name.",
    BlockReason.FORBIDDEN_FUNCTION: "The query uses a function that is not allowed.",
    BlockReason.REAL_DATE_FUNCTION: (
        "The query used the real current date. Dates must come from the business calendar."
    ),
    BlockReason.TABLE_NOT_ALLOWED: "The query uses data your role is not allowed to see.",
    BlockReason.COLUMN_NOT_ALLOWED: "The query uses a field your role is not allowed to see.",
    BlockReason.INVALID_LIMIT: "The query's row limit is not a plain number.",
}
