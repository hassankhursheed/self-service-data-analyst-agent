"""Agent settings from config/agent.yaml."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.charts import ChartConfig
from app.core.config import PROJECT_ROOT
from app.core.yaml_config import load_yaml_model
from app.semantic.verified import VerifiedConfig

AGENT_CONFIG_FILE = PROJECT_ROOT / "config" / "agent.yaml"

IntentPart = Literal["metric", "time_range", "entity", "grouping", "top_n"]


class IntentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    blocking_parts: list[IntentPart]
    default_period: str = Field(min_length=1)
    default_top_n: int = Field(ge=1)
    max_clarification_rounds: int = Field(ge=1, le=3)
    max_regenerations: int = Field(ge=0, le=2)
    fallback_metric_options: list[str] = Field(min_length=2)


class SqlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_regenerations: int = Field(ge=0, le=2)
    max_repair_attempts: int = Field(ge=0, le=5)
    repair_error_max_chars: int = Field(gt=0)
    db_connect_attempts: int = Field(ge=1, le=10)
    db_connect_backoff_seconds: float = Field(ge=0)


class AnswerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rows_for_llm: int = Field(ge=1, le=200)
    page_size: int = Field(ge=1, le=500)
    max_regenerations: int = Field(ge=0, le=2)
    low_confidence_label: str
    empty_suggestion: str
    chart: ChartConfig


class ConversationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_history_turns: int = Field(ge=0, le=20)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    graph_version: str
    intent: IntentConfig
    sql: SqlConfig
    answer: AnswerConfig
    verified_examples: VerifiedConfig
    conversation: ConversationConfig


def load_agent_config(path: Path = AGENT_CONFIG_FILE) -> AgentConfig:
    return load_yaml_model(path, AgentConfig)


@lru_cache
def get_agent_config() -> AgentConfig:
    return load_agent_config()
