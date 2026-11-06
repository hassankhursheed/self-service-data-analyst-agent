"""Seed the four application roles and the test users from brief section 7."""

from pathlib import Path

import psycopg
from pydantic import BaseModel, ConfigDict, model_validator

from app.core.config import PROJECT_ROOT, Settings
from app.core.enums import RegionCode, RoleName
from app.core.security import hash_password, verify_password
from app.core.yaml_config import load_yaml_model
from app.db.setup.northwind_data import SeedError
from app.safety.access_policy import AccessPolicy

TEST_USERS_FILE = PROJECT_ROOT / "config" / "test_users.yaml"


class TestUser(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str
    display_name: str
    role: RoleName | None
    region: RegionCode | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _region_matches_role(self) -> "TestUser":
        if (self.role is RoleName.SALES_MANAGER) != (self.region is not None):
            raise ValueError(f"{self.username}: only sales managers have a region (exactly one)")
        return self


class TestUsersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    users: list[TestUser]


def load_test_users(path: Path = TEST_USERS_FILE) -> TestUsersConfig:
    return load_yaml_model(path, TestUsersConfig)


def sync_roles(conn: psycopg.Connection, policy: AccessPolicy) -> dict[RoleName, int]:
    """Upsert app.roles from the access policy. Returns role ids by name."""
    ids: dict[RoleName, int] = {}
    with conn.transaction():
        for name, role in policy.roles.items():
            row = conn.execute(
                "INSERT INTO app.roles (name, db_role, description) VALUES (%s, %s, %s) "
                "ON CONFLICT (name) DO UPDATE SET db_role = EXCLUDED.db_role, "
                "description = EXCLUDED.description RETURNING id",
                (name.value, role.view_schema, role.description),
            ).fetchone()
            if row is None:
                raise SeedError(f"could not upsert role {name}")
            ids[name] = int(row[0])
    return ids


def sync_test_users(
    conn: psycopg.Connection,
    users: TestUsersConfig,
    role_ids: dict[RoleName, int],
    settings: Settings,
) -> int:
    """Create or update every test user; running twice changes nothing. Returns user count."""
    with conn.transaction():
        for user in users.users:
            secret = settings.demo_password(user.username)
            if secret is None or not secret.get_secret_value():
                env = "DEMO_PASSWORD_" + user.username.replace(".", "_").upper()
                raise SeedError(f"set {env} in the environment to seed {user.username}")
            password = secret.get_secret_value()
            row = conn.execute(
                "SELECT id, password_hash, is_active FROM app.users WHERE username = %s",
                (user.username,),
            ).fetchone()
            if row is None:
                created = conn.execute(
                    "INSERT INTO app.users (username, password_hash, display_name, is_active) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (user.username, hash_password(password), user.display_name, user.is_active),
                ).fetchone()
                if created is None:
                    raise SeedError(f"could not create user {user.username}")
                user_id = created[0]
            else:
                user_id, current_hash, was_active = row
                new_hash = (
                    current_hash
                    if verify_password(current_hash, password)
                    else hash_password(password)
                )
                # Disabling (or a password change) bumps token_version to revoke old tokens.
                revoke = (was_active and not user.is_active) or new_hash != current_hash
                conn.execute(
                    "UPDATE app.users SET display_name = %s, is_active = %s, password_hash = %s, "
                    "token_version = token_version + %s WHERE id = %s",
                    (user.display_name, user.is_active, new_hash, int(revoke), user_id),
                )
            if user.role is None:
                conn.execute("DELETE FROM app.user_roles WHERE user_id = %s", (user_id,))
            else:
                conn.execute(
                    "INSERT INTO app.user_roles (user_id, role_id) VALUES (%s, %s) "
                    "ON CONFLICT (user_id) DO UPDATE SET role_id = EXCLUDED.role_id",
                    (user_id, role_ids[user.role]),
                )
            keep = [user.region.value] if user.region else []
            conn.execute(
                "DELETE FROM app.user_regions WHERE user_id = %s AND NOT (region_code = ANY(%s))",
                (user_id, keep),
            )
            for code in keep:
                conn.execute(
                    "INSERT INTO app.user_regions (user_id, region_code) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (user_id, code),
                )
    return len(users.users)
