"""Unit tests for the application models and session factory (no database needed)."""

from pydantic import SecretStr
from sqlalchemy import CheckConstraint
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import PROJECT_ROOT, Settings
from app.core.enums import QuestionStatus
from app.db.erd import render_erd
from app.db.models import APP_SCHEMA, Base
from app.db.session import create_app_engine, create_session_factory

SECTION_21_TABLES = {
    "users", "roles", "user_roles", "user_regions",
    "conversations", "questions",
    "agent_runs", "agent_steps",
    "generated_queries", "query_executions", "blocked_queries",
    "clarifications", "feedback",
    "semantic_catalog", "metric_definitions", "business_calendar_config",
    "verified_queries",
    "eval_datasets", "eval_cases", "eval_runs", "eval_results",
    "audit_log", "agent_errors", "alerts",
}  # fmt: skip


def test_every_section_21_table_has_a_model() -> None:
    assert {t.name for t in Base.metadata.sorted_tables} == SECTION_21_TABLES


def test_all_tables_live_in_the_app_schema() -> None:
    assert {t.schema for t in Base.metadata.sorted_tables} == {APP_SCHEMA}


def test_every_table_has_created_at() -> None:
    missing = [t.name for t in Base.metadata.sorted_tables if "created_at" not in t.c]
    assert missing == []


def test_question_status_check_lists_every_state() -> None:
    table = Base.metadata.tables[f"{APP_SCHEMA}.questions"]
    checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
    status_check = next(str(c.sqltext) for c in checks if "status IN" in str(c.sqltext))
    assert all(f"'{status}'" in status_check for status in QuestionStatus)


def test_foreign_keys_stay_inside_the_app_schema() -> None:
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            assert fk.column.table.schema == APP_SCHEMA, fk.target_fullname


def test_app_engine_uses_pool_settings_from_config() -> None:
    settings = Settings(
        _env_file=None,
        app_database_url=SecretStr("postgresql+asyncpg://u:p@localhost:5433/db"),
        analytics_database_url=SecretStr("postgresql+asyncpg://r:p@localhost:5433/db"),
        jwt_secret_key=SecretStr("dummy"),
        postgres_user="dummy",
        postgres_password=SecretStr("dummy"),
    )
    engine = create_app_engine(settings)
    assert engine.pool.size() == settings.database.pool_size  # type: ignore[attr-defined]
    factory = create_session_factory(engine)
    assert factory.class_ is AsyncSession


def test_design_doc_erd_matches_the_models() -> None:
    doc = (PROJECT_ROOT / "docs" / "design" / "database-design.md").read_text("utf-8")
    block = doc.split("<!-- erd:start -->", 1)[1].split("<!-- erd:end -->", 1)[0]
    assert block.strip() == f"```mermaid\n{render_erd()}```", (
        "ERD is out of date: run python scripts/generate_erd.py"
    )
