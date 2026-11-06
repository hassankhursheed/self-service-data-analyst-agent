"""Versioned prompt templates loaded from config/prompts/<name>/<version>.yaml."""

from pathlib import Path
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import PROJECT_ROOT
from app.core.yaml_config import ConfigFileError, load_yaml_model

PROMPTS_DIR = PROJECT_ROOT / "config" / "prompts"


class PromptMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "human", "ai"]
    content: str = Field(min_length=1)


class PromptFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    version: str = Field(pattern=r"^v\d+$")
    description: str
    input_variables: list[str]
    messages: list[PromptMessage] = Field(min_length=1)

    @model_validator(mode="after")
    def _variables_match(self) -> "PromptFile":
        used = set(self.to_chat_prompt().input_variables)
        declared = set(self.input_variables)
        if used != declared:
            raise ValueError(
                f"input_variables {sorted(declared)} do not match the template {sorted(used)}"
            )
        return self

    def to_chat_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages([(m.role, m.content) for m in self.messages])

    @property
    def ref(self) -> str:
        """``name@version``, recorded with every run."""
        return f"{self.name}@{self.version}"


def load_prompt(name: str, version: str, prompts_dir: Path = PROMPTS_DIR) -> PromptFile:
    """Load one prompt by name and version; the file must agree with both."""
    path = prompts_dir / name / f"{version}.yaml"
    prompt = load_yaml_model(path, PromptFile)
    if (prompt.name, prompt.version) != (name, version):
        raise ConfigFileError(f"{path}: declares {prompt.ref}, expected {name}@{version}")
    return prompt
