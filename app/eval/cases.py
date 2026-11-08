"""The versioned evaluation set (eval/cases.yaml) as typed models."""

import datetime as dt
from collections import Counter
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import PROJECT_ROOT
from app.core.enums import CaseType, ExpectedBehaviour
from app.core.yaml_config import load_yaml_model

CASES_FILE = PROJECT_ROOT / "eval" / "cases.yaml"
DATASET_NAME = "northwind-eval"

# Minimum number of cases per type (brief §24).
MINIMUM_PER_TYPE: dict[CaseType, int] = {
    CaseType.SIMPLE: 15,
    CaseType.MEDIUM: 15,
    CaseType.HARD: 10,
    CaseType.AMBIGUOUS: 8,
    CaseType.UNSAFE: 6,
    CaseType.ACCESS_CONTROL: 6,
}
ANSWERABLE = (CaseType.SIMPLE, CaseType.MEDIUM, CaseType.HARD)


class EvalCaseDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[A-Z]-\d{2}$")
    type: CaseType
    test_user: str
    question: str = Field(min_length=3)
    expected_behaviour: ExpectedBehaviour
    expected_sql: str | None = None
    ordered: bool = False
    truth_sql: str | None = None
    leak_sql: str | None = None
    hidden_columns: list[str] = []
    notes: str | None = None

    @model_validator(mode="after")
    def _fields_fit_the_behaviour(self) -> Self:
        b = self.expected_behaviour
        if b is ExpectedBehaviour.CORRECT_RESULT and not self.expected_sql:
            raise ValueError(f"{self.id}: correct_result needs expected_sql")
        if b is ExpectedBehaviour.REGION_ONLY and not (self.truth_sql and self.leak_sql):
            raise ValueError(f"{self.id}: region_only needs truth_sql and leak_sql")
        if b is ExpectedBehaviour.EMPTY_RESULT and not self.leak_sql:
            raise ValueError(f"{self.id}: empty_result needs leak_sql")
        return self


class EvalCaseFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    reference_date: dt.date
    cases: list[EvalCaseDef]

    @model_validator(mode="after")
    def _unique_and_complete(self) -> Self:
        ids = [c.id for c in self.cases]
        duplicates = [i for i, n in Counter(ids).items() if n > 1]
        if duplicates:
            raise ValueError(f"duplicate case ids: {duplicates}")
        counts = Counter(c.type for c in self.cases)
        short = {t.value: n for t, n in MINIMUM_PER_TYPE.items() if counts[t] < n}
        if short:
            raise ValueError(f"not enough cases (minimum per type {short})")
        return self

    def select(
        self, ids: list[str] | None = None, types: list[CaseType] | None = None
    ) -> list[EvalCaseDef]:
        return [
            c for c in self.cases if (not ids or c.id in ids) and (not types or c.type in types)
        ]


def load_cases(path: Path = CASES_FILE) -> EvalCaseFile:
    return load_yaml_model(path, EvalCaseFile)
