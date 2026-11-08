"""Expected results of the evaluation cases, computed once and stored with the cases.

``python -m eval.check_cases --write`` runs each case's SQL (expected_sql as the test
user through the read-only role; truth_sql and leak_sql as the database owner) and saves
the rows to ``eval/expected/v<cases version>.json``. The runner compares against this
file, so evaluation never needs the owner account and the expected answers are
reviewable and versioned with the cases.
"""

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.config import PROJECT_ROOT

EXPECTED_DIR = PROJECT_ROOT / "eval" / "expected"

JsonValue = float | int | str | bool | None


class ResultSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    columns: list[str]
    rows: list[list[JsonValue]]


class CaseExpectation(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected: ResultSet | None = None
    truth: ResultSet | None = None
    leak: ResultSet | None = None


class ExpectedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    cases_version: int
    generated_at: dt.datetime
    cases: dict[str, CaseExpectation]


def json_value(value: Any) -> JsonValue:  # noqa: ANN401 (database cells have any type)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds() / 86400
    return str(value)


def result_set(columns: list[str], rows: list[tuple[Any, ...]] | list[list[Any]]) -> ResultSet:
    return ResultSet(columns=list(columns), rows=[[json_value(v) for v in row] for row in rows])


def expected_path(cases_version: int) -> Path:
    return EXPECTED_DIR / f"v{cases_version}.json"


def save_expected(data: ExpectedFile) -> Path:
    path = expected_path(data.cases_version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


class ExpectedMissing(Exception):
    pass


def load_expected(cases_version: int) -> ExpectedFile:
    path = expected_path(cases_version)
    if not path.exists():
        raise ExpectedMissing(
            f"{path.name} not found; run `python -m eval.check_cases --write` first"
        )
    return ExpectedFile.model_validate_json(path.read_text("utf-8"))
