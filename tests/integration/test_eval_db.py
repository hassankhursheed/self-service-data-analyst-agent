"""Step 22: the evaluation runner and API end to end (real database, scripted LLM).

The real model is not called in tests; the full run with the pinned model is done with
``python -m eval.run_eval`` (docs/evaluation.md).
"""

import dataclasses
import datetime as dt
import uuid
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.checkpoint import checkpoint_serializer
from app.agent.deps import AgentDeps
from app.api.deps import Services
from app.api.main import create_app
from app.core.config import Settings
from app.db.session import create_app_engine, create_session_factory
from app.eval.runner import EvalOptions, EvalRunner, RunAlreadyActive, get_eval_config
from scripts.seed import SeedSummary
from tests.fakes import ScriptedModel, fake_deps, intent, sql_reply
from tests.integration.test_api import assert_correlated, assert_error, login, running
from tests.integration.test_sql_path_db import real_executor

pytestmark = pytest.mark.integration
ORDERS_2024 = intent(summary="Number of orders in 2024", metric="number_of_orders")
AMBIGUOUS = intent(
    summary="Best customers",
    metric=None,
    metric_options=["revenue", "number_of_orders"],
    time_phrase=None,
    grouping="customer",
    missing=[{"part": "metric", "reason": "best could mean revenue or number of orders"}],
    clarifying_question="Best by revenue or by number of orders?",
    options=["By revenue", "By number of orders"],
)
COUNT_SQL = sql_reply(
    "SELECT COUNT(DISTINCT o.order_id) AS orders FROM orders o "
    "WHERE o.order_date BETWEEN '2024-01-01' AND '2024-12-31'",
    ["orders"],
    metrics_used=["number_of_orders"],
)
ANSWER = {"explanation": "There were 408 orders in 2024.", "sql_description": "Counts orders."}
CASES = ["S-02", "U-01", "X-04", "A-01"]


def model() -> ScriptedModel:
    # LLM calls in case order: S-02 (intent, SQL, answer), A-01 (intent). U-01 and X-04 are
    # refused by the guardrails before any model call.
    return ScriptedModel(ORDERS_2024, AMBIGUOUS, sql=[COUNT_SQL], answer=[ANSWER])


class FakeLangSmith:
    def __init__(self) -> None:
        self.examples: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []
        self.feedback: list[tuple[uuid.UUID, float]] = []

    def has_dataset(self, dataset_name: str) -> bool:
        return False

    def create_dataset(self, dataset_name: str, description: str) -> Any:  # noqa: ANN401
        return type("D", (), {"id": uuid.uuid4(), "name": dataset_name})()

    def list_examples(self, dataset_id: object) -> list[Any]:
        return []

    def create_examples(self, **kwargs: Any) -> dict[str, list[str]]:  # noqa: ANN401
        self.examples = [
            dict(i, **m) for i, m in zip(kwargs["inputs"], kwargs["metadata"], strict=True)
        ]
        return {"example_ids": [str(uuid.uuid4()) for _ in self.examples]}

    def has_project(self, name: str) -> bool:
        return False

    def create_project(self, name: str, **kwargs: Any) -> None:  # noqa: ANN401
        self.project = name

    def create_run(self, **kwargs: Any) -> None:  # noqa: ANN401
        self.runs.append(kwargs)

    def create_feedback(self, run_id: uuid.UUID, key: str, score: float, comment: str) -> None:
        self.feedback.append((run_id, score))


@pytest.fixture
async def deps(
    settings: Settings,
    seeded: SeedSummary,
    analytics_engine: AsyncEngine,
    owner_conn: psycopg.Connection,
) -> AsyncIterator[AgentDeps]:
    started = dt.datetime.now(dt.UTC)
    yield fake_deps(model(), real_executor(analytics_engine))
    owner_conn.execute("DELETE FROM app.eval_runs WHERE started_at >= %s", (started,))
    owner_conn.execute("DELETE FROM app.audit_log WHERE occurred_at >= %s", (started,))


async def test_the_runner_scores_cases_records_settings_and_uploads(
    settings: Settings,
    deps: AgentDeps,
    owner_conn: psycopg.Connection,
) -> None:
    engine = create_app_engine(settings)
    fake = FakeLangSmith()
    runner = EvalRunner(
        create_session_factory(engine),
        lambda: deps,
        langsmith_client=fake,
        config=get_eval_config().model_copy(update={"pause_between_cases_seconds": 0}),
    )
    options = EvalOptions(experiment_name="test-run", case_ids=CASES)
    run_id = await runner.create_run(options)
    with pytest.raises(RunAlreadyActive):
        await runner.create_run(options)
    metrics = await runner.execute(run_id, options)
    await engine.dispose()

    assert metrics is not None
    assert metrics.cases_total == 4
    assert metrics.execution_accuracy == 1.0  # S-02: 408 orders
    assert metrics.clarification_rate == 1.0  # A-01 asked
    assert metrics.unsafe_blocked_rate == 1.0  # U-01 blocked before any SQL
    assert metrics.access_control_pass_rate == 1.0  # X-04 no role: rejected
    assert metrics.access_leaks == 0
    assert metrics.ungrounded_answers == 0

    run = owner_conn.execute(
        "SELECT status, model_name, temperature, reference_date, verified_examples_enabled, "
        "semantic_version, settings, cases_passed, execution_accuracy FROM app.eval_runs "
        "WHERE id = %s",
        (run_id,),
    ).fetchone()
    assert run is not None
    status, model_name, temperature, reference, verified, semantic, run_settings, passed, acc = run
    assert (status, model_name, float(temperature)) == ("completed", get_eval_config().model, 0.0)
    assert str(reference) == "2025-05-06"
    assert verified is True
    assert semantic.endswith(":full")
    assert run_settings["cases_version"] == 1
    assert sorted(run_settings["case_ids"]) == sorted(CASES)
    assert run_settings["langsmith"]["status"] == "uploaded"
    assert (passed, float(acc)) == (4, 1.0)

    results = owner_conn.execute(
        "SELECT c.case_key, r.passed, r.final_status, r.details->>'status' FROM app.eval_results r "
        "JOIN app.eval_cases c ON c.id = r.case_id WHERE r.run_id = %s ORDER BY c.case_key",
        (run_id,),
    ).fetchall()
    assert [(k, p, s) for k, p, s, _ in results] == [
        ("A-01", True, "CLARIFICATION_NEEDED"),
        ("S-02", True, "ANSWERED"),
        ("U-01", True, results[2][2]),
        ("X-04", True, "REJECTED"),
    ]
    assert results[2][2] in ("BLOCKED", "REJECTED")
    # Evaluation questions are not written to the audit tables.
    audited = owner_conn.execute(
        "SELECT count(*) FROM app.questions "
        "WHERE question_text = 'How many orders were placed in 2024?' "
        "AND created_at >= now() - interval '5 minutes'"
    ).fetchone()
    assert audited == (0,)
    # LangSmith: one example per case in the dataset, one scored run per case.
    assert len(fake.examples) == 60
    assert len(fake.runs) == 4
    assert all(score == 1.0 for _, score in fake.feedback)


async def test_the_api_starts_lists_and_shows_runs(
    settings: Settings,
    deps: AgentDeps,
    owner_conn: psycopg.Connection,
) -> None:
    app = create_app(
        settings, agent_deps=deps, checkpointer=InMemorySaver(serde=checkpoint_serializer())
    )
    async with running(app) as client:
        admin = await login(client, settings, "admin")
        bad = await client.post(
            "/admin/eval/run", headers=admin, json={"dataset": "other", "experiment_name": "x"}
        )
        assert_error(bad, 400, "VALIDATION_ERROR")
        started = await client.post(
            "/admin/eval/run",
            headers=admin,
            json={
                "dataset": "northwind-eval",
                "experiment_name": "api-run",
                "subset": ["S-02", "U-01"],
            },
        )
        assert started.status_code == 202, started.text
        assert_correlated(started)
        run_id = started.json()["run_id"]
        services: Services = app.state.services
        await services.evaluation.wait()

        listing = await client.get("/admin/eval/runs", headers=admin)
        assert listing.status_code == 200
        mine = next(r for r in listing.json()["items"] if r["run_id"] == run_id)
        assert mine["status"] == "completed"
        assert mine["progress"] == 2
        assert listing.json()["targets"]["execution_accuracy"] == 0.8

        detail = await client.get(f"/admin/eval/runs/{run_id}", headers=admin)
        assert detail.status_code == 200
        assert_correlated(detail)
        assert {r["case_key"] for r in detail.json()["results"]} == {"S-02", "U-01"}
        s02 = next(r for r in detail.json()["results"] if r["case_key"] == "S-02")
        assert s02["details"]["expected"]["rows"] == [[408]]
        assert s02["details"]["actual"]["rows"] == [[408]]
        assert_error(
            await client.get(f"/admin/eval/runs/{uuid.uuid4()}", headers=admin), 404, "NOT_FOUND"
        )
        finance = await login(client, settings, "finance")
        assert_error(await client.get("/admin/eval/runs", headers=finance), 403, "ADMIN_ONLY")


async def test_an_interrupted_run_is_marked_failed_at_startup(
    settings: Settings,
    deps: AgentDeps,
    owner_conn: psycopg.Connection,
) -> None:
    engine = create_app_engine(settings)
    runner = EvalRunner(create_session_factory(engine), lambda: deps)
    run_id = await runner.create_run(EvalOptions(experiment_name="left-running", case_ids=["S-01"]))
    assert await runner.mark_interrupted() == 1
    await engine.dispose()
    row = owner_conn.execute(
        "SELECT status, error_message FROM app.eval_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert "interrupted" in row[1]


async def test_names_only_and_no_examples_change_the_recorded_settings(
    settings: Settings,
    deps: AgentDeps,
    owner_conn: psycopg.Connection,
) -> None:
    engine = create_app_engine(settings)
    runner = EvalRunner(create_session_factory(engine), lambda: dataclasses.replace(deps))
    run_id = await runner.create_run(
        EvalOptions(
            experiment_name="bare",
            verified_examples_enabled=False,
            semantic_mode="names_only",
            case_ids=["S-01"],
        )
    )
    await runner.mark_interrupted()
    await engine.dispose()
    row = owner_conn.execute(
        "SELECT verified_examples_enabled, semantic_version, settings->>'semantic_mode' "
        "FROM app.eval_runs WHERE id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    assert row[0] is False
    assert row[1].endswith(":names_only")
    assert row[2] == "names_only"
