"""Application settings.

Values are loaded from, highest priority first:

1. arguments passed to ``Settings(...)`` (used by tests),
2. environment variables,
3. the ``.env`` file in the project root (local development only, gitignored),
4. ``config/app.yaml`` (non-secret, versioned),
5. defaults defined here.

Secrets are typed as ``SecretStr`` and must come from the environment, never from
``config/app.yaml``. Nested YAML values can be overridden with ``__``, for example
``APP__LOG_LEVEL=DEBUG``.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from psycopg.conninfo import make_conninfo
from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from sqlalchemy import URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config" / "app.yaml"
ENV_FILE = PROJECT_ROOT / ".env"


class AppConfig(BaseModel):
    """Non-secret application metadata (``app`` section of config/app.yaml)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class DatabasePoolConfig(BaseModel):
    """Connection pool limits (``database`` section of config/app.yaml)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout_seconds: float = 30
    pool_recycle_seconds: int = 1800
    connect_timeout_seconds: float = 10


class Settings(BaseSettings):
    """All settings for the application, validated at startup."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        frozen=True,
        yaml_file=CONFIG_FILE,
        yaml_file_encoding="utf-8",
    )

    # --- From config/app.yaml (non-secret, versioned) ---
    config_version: int
    app: AppConfig
    database: DatabasePoolConfig = DatabasePoolConfig()

    # --- From the environment (secrets and deployment-specific values) ---
    app_env: Literal["development", "test", "production"] = "development"
    # PostgreSQL server and owner credentials (used by Docker Compose, seed and migrations;
    # never by the running agent).
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "northwind"
    postgres_user: str
    postgres_password: SecretStr
    # Two separate database roles (brief section 27): the application role for app data,
    # and a read-only analytics role for the agent.
    app_database_url: SecretStr
    analytics_database_url: SecretStr
    jwt_secret_key: SecretStr
    llm_api_key: SecretStr | None = None
    # Standard LangSmith SDK variable names, so one variable serves both.
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "self-service-data-analyst-agent"

    def owner_conninfo(self) -> str:
        """libpq connection string for the database owner (seed, migrations, checks)."""
        return make_conninfo(
            host=self.postgres_host,
            port=self.postgres_port,
            dbname=self.postgres_db,
            user=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
        )

    def owner_sqlalchemy_url(self) -> URL:
        """SQLAlchemy URL (psycopg driver) for the database owner."""
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Add config/app.yaml as the lowest-priority source after .env."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once."""
    return Settings()
