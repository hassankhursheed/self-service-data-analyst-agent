"""Pydantic schema for config/semantic/semantic_layer.yaml (unknown keys fail)."""

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import RoleName

_IDENT = r"^[a-z][a-z0-9_]*$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ColumnDef(_Strict):
    description: str = Field(min_length=1)
    examples: list[str] = []
    allowed_roles: list[RoleName]


class TableDef(_Strict):
    description: str = Field(min_length=1)
    allowed_roles: list[RoleName]
    columns: dict[str, ColumnDef] = Field(min_length=1)


class JoinDef(_Strict):
    left: str = Field(pattern=_IDENT)
    right: str = Field(pattern=_IDENT)
    condition: str = Field(min_length=1)

    @property
    def key(self) -> str:
        return f"{self.left}->{self.right}"


class MetricDef(_Strict):
    description: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    tables: list[str] = Field(min_length=1)  # "<table> <alias>", e.g. "orders o"
    join: str | None = None
    synonyms: list[str] = []
    allowed_roles: list[RoleName]

    @property
    def table_names(self) -> list[str]:
        return [t.split()[0] for t in self.tables]


class SemanticLayer(_Strict):
    version: int = Field(ge=1)
    tables: dict[str, TableDef] = Field(min_length=1)
    joins: list[JoinDef]
    metrics: dict[str, MetricDef]
    # Business term -> "table:<t>", "column:<t>.<c>" or "metric:<m>".
    synonyms: dict[str, str]

    @model_validator(mode="after")
    def _references_exist(self) -> "SemanticLayer":
        for name in self.tables:
            if not re.match(_IDENT, name):
                raise ValueError(f"invalid table name {name!r}")
        for table_name, table in self.tables.items():
            for col_name, col in table.columns.items():
                extra = set(col.allowed_roles) - set(table.allowed_roles)
                if extra:
                    raise ValueError(
                        f"column {table_name}.{col_name} allows roles the table does not: "
                        f"{sorted(extra)}"
                    )
        for join in self.joins:
            for side in (join.left, join.right):
                if side not in self.tables:
                    raise ValueError(f"join {join.key} uses unknown table {side!r}")
        for metric_name, metric in self.metrics.items():
            for used in metric.table_names:
                if used not in self.tables:
                    raise ValueError(f"metric {metric_name} uses unknown table {used!r}")
            if len(metric.tables) > 1 and not metric.join:
                raise ValueError(f"metric {metric_name} uses several tables but has no join")
        for term, target in self.synonyms.items():
            if not self._target_exists(target):
                raise ValueError(f"synonym {term!r} points to unknown target {target!r}")
        return self

    def _target_exists(self, target: str) -> bool:
        kind, _, name = target.partition(":")
        if kind == "table":
            return name in self.tables
        if kind == "metric":
            return name in self.metrics
        if kind == "column":
            table, _, column = name.partition(".")
            return table in self.tables and column in self.tables[table].columns
        return False
