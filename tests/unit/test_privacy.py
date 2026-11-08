"""Step 24: personal data never reaches the LLM prompt or the LangSmith traces."""

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from pydantic import SecretStr

from app.agent.graph import Agent
from app.agent.nodes.answer import personal_columns, rows_text
from app.agent.state import AgentRequest
from app.agent.tracing import redacted_tracing, redacting_client, tracing_enabled
from app.core.config import Settings
from app.core.enums import RoleName
from app.core.masking import redact_for_trace
from app.db.analytics import QueryResult
from tests.fakes import ScriptedModel, fake_deps, intent


def settings(**fields: Any) -> Settings:  # noqa: ANN401
    base: dict[str, Any] = {
        "_env_file": None,
        "app_database_url": SecretStr("postgresql+asyncpg://a:b@h/d"),
        "analytics_database_url": SecretStr("postgresql+asyncpg://a:b@h/d"),
        "jwt_secret_key": SecretStr("x"),
        "postgres_user": "o",
        "postgres_password": SecretStr("p"),
        "langsmith_tracing": False,
        "langsmith_api_key": None,
    }
    base.update(fields)
    return Settings(**base)


def test_personal_columns_come_from_the_access_policy() -> None:
    hidden = personal_columns()
    assert {"contact_name", "phone", "address", "birth_date", "home_phone"} <= hidden
    assert "company_name" not in hidden
    assert "country" not in hidden  # also a business column (customers, orders)
    assert {"city", "region"}.isdisjoint(hidden)


def test_the_answer_prompt_never_contains_personal_column_values() -> None:
    result = QueryResult(
        columns=["company_name", "contact_name", "phone", "revenue"],
        rows=[("Alfreds Futterkiste", "Maria Anders", "030-0074321", 4273.0)],
        row_count=1,
        truncated=False,
    )
    text = rows_text(result, 5, personal_columns())
    assert "Alfreds Futterkiste" in text
    assert "4,273" in text
    assert "Maria Anders" not in text
    assert "030-0074321" not in text
    assert text.count("[PERSONAL]") == 2


def test_traces_get_row_counts_and_masked_strings_only() -> None:
    traced = redact_for_trace(
        {
            "question": "call me on +44 20 7946 0958",
            "execution": {
                "columns": ["contact_name"],
                "rows": [["Maria Anders"], ["Ana Trujillo"]],
            },
            "nested": [{"rows": [[1], [2], [3]]}],
            "count": 3,
        }
    )
    assert traced["execution"]["rows"] == "[2 rows not traced]"
    assert traced["nested"][0]["rows"] == "[3 rows not traced]"
    assert "7946 0958" not in traced["question"]
    assert traced["count"] == 3
    assert "Maria Anders" not in str(traced)


def test_the_redacting_client_exists_only_when_tracing_is_on() -> None:
    assert redacting_client(settings()) is None
    assert not tracing_enabled(
        settings(langsmith_tracing=True, langsmith_api_key=SecretStr("CHANGE_ME"))
    )
    client = redacting_client(
        settings(langsmith_tracing=True, langsmith_api_key=SecretStr("lsv2_pt_test_key_not_real"))
    )
    assert client is not None
    assert client._hide_inputs is redact_for_trace
    assert client._hide_outputs is redact_for_trace


def test_redacted_tracing_puts_the_client_in_the_tracing_context() -> None:
    from langsmith.run_helpers import get_tracing_context

    sentinel = object()
    with redacted_tracing(sentinel):
        assert get_tracing_context()["client"] is sentinel
    with redacted_tracing(None):
        assert get_tracing_context()["client"] is None


async def test_every_graph_run_is_traced_through_the_redacting_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    used: list[object] = []

    @contextmanager
    def record(client: object) -> Iterator[None]:
        used.append(client)
        yield

    monkeypatch.setattr("app.agent.graph.redacted_tracing", record)
    client = object()
    deps = dataclasses.replace(fake_deps(ScriptedModel(intent())), trace_client=client)
    request = AgentRequest(
        username="finance",
        role=RoleName.FINANCE_ANALYST,
        is_active=True,
        question="Total revenue in 2024",
    )
    await Agent(deps).run(request)
    assert used == [client]


def test_log_records_are_masked_including_tracebacks(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from app.core.log_masking import install_log_masking

    install_log_masking()
    install_log_masking()  # idempotent
    log = logging.getLogger("test.privacy")
    with caplog.at_level(logging.INFO, logger="test.privacy"):
        log.info("login for %s from %s", "maria.anders@example.com", "+44 20 7946 0958")
        try:
            raise RuntimeError("connect failed: postgresql://app_rw:s3cret-pass@db:5432/x")
        except RuntimeError:
            log.exception("database problem")
    text = caplog.text + "".join(r.exc_text or "" for r in caplog.records)
    assert "maria.anders@example.com" not in text
    assert "7946 0958" not in text
    assert "s3cret-pass" not in text
    assert "RuntimeError" in text  # the traceback is kept, only values are masked


def test_clean_records_keep_their_arguments_for_formatters_like_uvicorn() -> None:
    """Step 26 walk-through: emptying args broke uvicorn's access log on every request."""
    import logging

    from app.core.log_masking import mask_record

    access = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.5:5000", "GET", "/health", "1.1", 200), None,
    )  # fmt: skip
    masked = mask_record(access)
    assert masked.args == ("10.0.0.5:5000", "GET", "/health", "1.1", 200)
    leaky = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.5:5000", "GET", "/users?email=maria.anders@example.com", "1.1", 200), None,
    )  # fmt: skip
    masked = mask_record(leaky)
    assert isinstance(masked.args, tuple)
    assert len(masked.args) == 5  # still unpackable by the access formatter
    assert "maria.anders@example.com" not in masked.getMessage()
