"""Rule-based input guardrails (N-02). Patterns live in config/guardrails.yaml.

Order of checks: length -> prompt injection -> data-change request -> personal data
(role-aware) -> off-topic -> scope-override flag. The first failing check decides.
"""

import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import PROJECT_ROOT
from app.core.enums import BlockReason, QuestionStatus, RoleName
from app.core.yaml_config import load_yaml_model
from app.safety.access_policy import AccessPolicy, get_access_policy
from app.safety.question_check import validate_question
from app.safety.sql_policy import BLOCK_MESSAGES, SqlPolicy, get_sql_policy

GUARDRAILS_FILE = PROJECT_ROOT / "config" / "guardrails.yaml"


def _compile(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"invalid pattern {pattern!r}: {exc}") from exc


class PersonalDataRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pattern: str
    table: str | None
    column: str | None

    @field_validator("pattern")
    @classmethod
    def _valid(cls, value: str) -> str:
        _compile(value)
        return value


class GuardrailsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    prompt_injection: list[str]
    scope_override: list[str]
    scope_override_notice: str
    write_request: list[str]
    personal_data: list[PersonalDataRule]
    off_topic: list[str]

    @field_validator("prompt_injection", "scope_override", "write_request", "off_topic")
    @classmethod
    def _valid_patterns(cls, values: list[str]) -> list[str]:
        for value in values:
            _compile(value)
        return values


def load_guardrails(path: Path = GUARDRAILS_FILE) -> GuardrailsConfig:
    return load_yaml_model(path, GuardrailsConfig)


@lru_cache
def get_guardrails() -> GuardrailsConfig:
    return load_guardrails()


class GuardrailResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    passed: bool
    status: QuestionStatus
    question: str
    reason_code: BlockReason | None = None
    user_message: str | None = None
    matched_rule: str | None = None
    flags: list[str] = []
    notices: list[str] = []


def _first_match(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        if _compile(pattern).search(text):
            return pattern
    return None


def _refuse(
    question: str, status: QuestionStatus, reason: BlockReason, rule: str
) -> GuardrailResult:
    return GuardrailResult(
        passed=False,
        status=status,
        question=question,
        reason_code=reason,
        user_message=BLOCK_MESSAGES[reason],
        matched_rule=rule,
    )


def check_input(
    question: str,
    role: RoleName,
    config: GuardrailsConfig | None = None,
    policy: AccessPolicy | None = None,
    sql_policy: SqlPolicy | None = None,
) -> GuardrailResult:
    """Decide whether a question may continue to the agent."""
    config = config or get_guardrails()
    policy = policy or get_access_policy()
    length = validate_question(question, sql_policy or get_sql_policy())
    text = length.question
    if not length.allowed and length.reason_code is not None:
        return _refuse(text, QuestionStatus.REJECTED, length.reason_code, "length")

    rule = _first_match(config.prompt_injection, text)
    if rule:
        return _refuse(text, QuestionStatus.BLOCKED, BlockReason.PROMPT_INJECTION, rule)

    rule = _first_match(config.write_request, text)
    if rule:
        return _refuse(text, QuestionStatus.BLOCKED, BlockReason.WRITE_REQUEST, rule)

    for item in config.personal_data:
        if not _compile(item.pattern).search(text):
            continue
        hidden = (
            item.table is None
            or item.column is None
            or not policy.is_column_visible(role, item.table, item.column)
        )
        if hidden:
            return _refuse(
                text, QuestionStatus.BLOCKED, BlockReason.PERSONAL_DATA_REQUEST, item.pattern
            )

    rule = _first_match(config.off_topic, text)
    if rule:
        return _refuse(text, QuestionStatus.REJECTED, BlockReason.OFF_TOPIC, rule)

    flags: list[str] = []
    notices: list[str] = []
    # Asking for "all regions" only widens scope for region-scoped roles.
    scoped = policy.roles[role].region_scoped
    patterns = [p for p in config.scope_override if scoped or "region" not in p]
    rule = _first_match(patterns, text)
    if rule:
        flags.append("scope_override_attempt")
        notices.append(config.scope_override_notice)
    return GuardrailResult(
        passed=True,
        status=QuestionStatus.GUARDRAIL_CHECKED,
        question=text,
        matched_rule=rule,
        flags=flags,
        notices=notices,
    )
