"""Access policy: which tables, columns and rows each business role may see.

Loaded from config/access_policy.yaml. Used by the seed script to build the secure views
and, later, by SQL validation for allow-lists.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import PROJECT_ROOT
from app.core.enums import RoleName
from app.core.yaml_config import load_yaml_model

ACCESS_POLICY_FILE = PROJECT_ROOT / "config" / "access_policy.yaml"

# Region key column -> analytics lookup view that maps it to a region.
REGION_LOOKUPS: dict[str, str] = {
    "customer_id": "customer_regions",
    "order_id": "order_regions",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RolePolicy(_Strict):
    description: str
    view_schema: str | None = Field(pattern=r"^[a-z_]+$")
    region_scoped: bool
    tables: list[str]


class SensitiveColumn(_Strict):
    visible_to: list[RoleName]
    reason: str


class AccessPolicy(_Strict):
    version: int
    roles: dict[RoleName, RolePolicy]
    region_keys: dict[str, str]
    sensitive_columns: dict[str, dict[str, SensitiveColumn]]

    @model_validator(mode="after")
    def _consistent(self) -> "AccessPolicy":
        missing = set(RoleName) - set(self.roles)
        if missing:
            raise ValueError(f"roles missing from the policy: {sorted(missing)}")
        for table, key in self.region_keys.items():
            if key not in REGION_LOOKUPS:
                raise ValueError(f"region key {table}.{key} has no lookup view")
        for role, policy in self.roles.items():
            if policy.tables and policy.view_schema is None:
                raise ValueError(f"role {role} has tables but no view_schema")
        return self

    def tables_for(self, role: RoleName) -> list[str]:
        return list(self.roles[role].tables)

    def is_column_visible(self, role: RoleName, table: str, column: str) -> bool:
        if table not in self.roles[role].tables:
            return False
        rule = self.sensitive_columns.get(table, {}).get(column)
        return rule is None or role in rule.visible_to

    def visible_columns(self, role: RoleName, table: str, columns: list[str]) -> list[str]:
        """Filter ``columns`` (in order) to those ``role`` may see in ``table``."""
        return [c for c in columns if self.is_column_visible(role, table, c)]

    def business_roles(self) -> list[RoleName]:
        """Roles that query business data (they have a view schema)."""
        return [role for role, p in self.roles.items() if p.view_schema is not None]


def load_access_policy(path: Path = ACCESS_POLICY_FILE) -> AccessPolicy:
    return load_yaml_model(path, AccessPolicy)


@lru_cache
def get_access_policy() -> AccessPolicy:
    return load_access_policy()
