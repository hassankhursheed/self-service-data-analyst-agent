"""Unit tests for app.core.config."""

import os
from typing import get_args

import pytest
import yaml
from psycopg.conninfo import conninfo_to_dict
from pydantic import BaseModel, SecretStr, ValidationError

from app.core.config import CONFIG_FILE, PROJECT_ROOT, Settings

DUMMY_ENV = {
    "APP_DATABASE_URL": "postgresql+asyncpg://app:dummy@localhost:5432/test",
    "ANALYTICS_DATABASE_URL": "postgresql+asyncpg://ro:dummy@localhost:5432/test",
    "JWT_SECRET_KEY": "dummy-jwt-secret-for-tests",
    "POSTGRES_USER": "dummy_owner",
    "POSTGRES_PASSWORD": "dummy-owner-password",
}


def _load() -> Settings:
    """Load settings while ignoring any local .env file, so tests are repeatable."""
    return Settings(_env_file=None)


def _yaml_paths(node: object, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if not isinstance(node, dict):
        return set()
    paths: set[tuple[str, ...]] = set()
    for key, value in node.items():
        path = (*prefix, str(key))
        paths.add(path)
        paths |= _yaml_paths(value, path)
    return paths


def _secret_paths(model: type[BaseModel], prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for name, field in model.model_fields.items():
        path = (*prefix, name)
        types = (field.annotation, *get_args(field.annotation))
        if SecretStr in types:
            paths.add(path)
        for tp in types:
            if isinstance(tp, type) and issubclass(tp, BaseModel):
                paths |= _secret_paths(tp, path)
    return paths


def _yaml_top_level_keys() -> set[str]:
    return {path[0] for path in _yaml_paths(yaml.safe_load(CONFIG_FILE.read_text("utf-8")))}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove settings variables from the real environment, then set dummy secrets."""
    fields = set(Settings.model_fields)
    for key in list(os.environ):
        lowered = key.lower()
        if lowered in fields or any(lowered.startswith(f"{f}__") for f in fields):
            monkeypatch.delenv(key)
    for key, value in DUMMY_ENV.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_settings_import_and_load(clean_env: pytest.MonkeyPatch) -> None:
    settings = _load()
    assert settings.app.name == "AskData - Self-Service Data Analyst Agent"
    assert settings.app_env == "development"
    assert settings.langsmith_tracing is False
    assert settings.app_database_url.get_secret_value() == DUMMY_ENV["APP_DATABASE_URL"]


def test_environment_variable_overrides_yaml(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP__LOG_LEVEL", "DEBUG")
    assert _load().app.log_level == "DEBUG"


def test_missing_secret_fails_fast(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.delenv("APP_DATABASE_URL")
    with pytest.raises(ValidationError, match="app_database_url"):
        _load()


def test_secret_values_are_masked(clean_env: pytest.MonkeyPatch) -> None:
    settings = _load()
    text = repr(settings) + str(settings)
    secret_names = {path[0].upper() for path in _secret_paths(Settings)}
    for key, value in DUMMY_ENV.items():
        if key in secret_names:
            assert value not in text


def test_owner_conninfo_uses_owner_settings(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("POSTGRES_PORT", "6000")
    settings = _load()
    assert conninfo_to_dict(settings.owner_conninfo()) == {
        "host": "localhost",
        "port": "6000",
        "dbname": "northwind",
        "user": "dummy_owner",
        "password": "dummy-owner-password",
    }
    url = settings.owner_sqlalchemy_url()
    assert (url.drivername, url.port, url.username) == ("postgresql+psycopg", 6000, "dummy_owner")


def test_yaml_holds_no_secret_settings() -> None:
    secrets = _secret_paths(Settings)
    assert secrets, "expected at least one SecretStr field"
    yaml_paths = _yaml_paths(yaml.safe_load(CONFIG_FILE.read_text("utf-8")))
    assert not secrets & yaml_paths


def test_env_example_lists_every_environment_variable() -> None:
    lines = (PROJECT_ROOT / ".env.example").read_text("utf-8").splitlines()
    documented = {
        line.split("=", 1)[0].strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    }
    env_fields = set(Settings.model_fields) - _yaml_top_level_keys()
    # Read by other services, not by the Python settings (the Next.js UI server).
    other_services = {"API_BASE_URL"}
    assert documented == {name.upper() for name in env_fields} | other_services
