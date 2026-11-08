"""Upload the evaluation dataset and each run's results to LangSmith (brief §24).

The dataset ``<name>-v<cases version>`` holds one example per case (question, test user,
expected behaviour and expected rows). Each evaluation run becomes a LangSmith experiment
project with one run per case, linked to its example and scored with ``passed`` feedback.
LangSmith is optional: without ``LANGSMITH_API_KEY`` the upload is skipped (and the run
records that); an upload problem never fails the evaluation itself.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Sequence
from typing import Any, Protocol

from app.core.config import Settings
from app.eval.cases import EvalCaseFile
from app.eval.expected import ExpectedFile

logger = logging.getLogger(__name__)
PLACEHOLDERS = {"", "CHANGE_ME"}
# langsmith.Client; kept loose so tests can pass a small fake.
LangSmithClient = Any


class CaseResult(Protocol):
    """What the sync needs from one case outcome."""

    @property
    def case_id(self) -> str: ...
    @property
    def passed(self) -> bool: ...
    @property
    def status(self) -> str | None: ...
    @property
    def reason(self) -> str: ...
    @property
    def latency_ms(self) -> int: ...


def _expected_rows(expected: ExpectedFile, case_id: str) -> dict[str, Any] | None:
    found = expected.cases[case_id].expected or expected.cases[case_id].truth
    return found.model_dump() if found is not None else None


def langsmith_configured(settings: Settings) -> bool:
    key = settings.langsmith_api_key.get_secret_value() if settings.langsmith_api_key else ""
    return key not in PLACEHOLDERS


def make_client(settings: Settings) -> LangSmithClient:
    from langsmith import Client

    if settings.langsmith_api_key is None:
        raise ValueError("LANGSMITH_API_KEY is not set")
    return Client(
        api_key=settings.langsmith_api_key.get_secret_value(), api_url=settings.langsmith_endpoint
    )


def dataset_name(base: str, cases: EvalCaseFile) -> str:
    return f"{base}-v{cases.version}"


def upload_dataset(
    client: LangSmithClient,
    base: str,
    cases: EvalCaseFile,
    expected: ExpectedFile,
) -> tuple[str, dict[str, str]]:
    """Create the dataset once; return its ID and the example ID per case."""
    name = dataset_name(base, cases)
    if client.has_dataset(dataset_name=name):
        dataset = client.read_dataset(dataset_name=name)
    else:
        dataset = client.create_dataset(
            dataset_name=name,
            description=f"Northwind data analyst evaluation set, cases version {cases.version} "
            f"(reference date {cases.reference_date}).",
        )
    examples = {
        (ex.metadata or {}).get("case_id"): str(ex.id)
        for ex in client.list_examples(dataset_id=dataset.id)
    }
    missing = [c for c in cases.cases if c.id not in examples]
    if missing:
        created = client.create_examples(
            dataset_id=dataset.id,
            inputs=[{"question": c.question, "test_user": c.test_user} for c in missing],
            outputs=[
                {
                    "expected_behaviour": c.expected_behaviour.value,
                    "expected": _expected_rows(expected, c.id),
                }
                for c in missing
            ],
            metadata=[
                {"case_id": c.id, "type": c.type.value, "ordered": c.ordered} for c in missing
            ],
        )
        ids = created.get("example_ids", []) if isinstance(created, dict) else []
        if len(ids) != len(missing):
            examples = {
                (ex.metadata or {}).get("case_id"): str(ex.id)
                for ex in client.list_examples(dataset_id=dataset.id)
            }
        else:
            examples.update({c.id: str(i) for c, i in zip(missing, ids, strict=True)})
    return str(dataset.id), {k: v for k, v in examples.items() if k}


def log_experiment(
    client: LangSmithClient,
    project: str,
    examples: dict[str, str],
    results: Sequence[CaseResult],
    metadata: dict[str, Any],
) -> None:
    """One LangSmith project per run; one run and one 'passed' score per case."""
    if not client.has_project(project):
        client.create_project(project, metadata=metadata, reference_dataset_id=None)
    now = dt.datetime.now(dt.UTC)
    for r in results:
        run_id = uuid.uuid4()
        client.create_run(
            id=run_id,
            name=r.case_id,
            run_type="chain",
            project_name=project,
            inputs={"case_id": r.case_id},
            outputs={"status": r.status, "reason": r.reason},
            reference_example_id=examples.get(r.case_id),
            start_time=now - dt.timedelta(milliseconds=r.latency_ms),
            end_time=now,
            extra={"metadata": metadata},
        )
        client.create_feedback(
            run_id, key="passed", score=1.0 if r.passed else 0.0, comment=r.reason
        )


def sync_run(
    settings: Settings | None,
    base_name: str,
    cases: EvalCaseFile,
    expected: ExpectedFile,
    experiment: str,
    run_id: uuid.UUID,
    results: Sequence[CaseResult],
    metadata: dict[str, Any],
    client: LangSmithClient = None,
) -> dict[str, Any]:
    """Upload and log; return what to record in the run's settings."""
    if client is None and (settings is None or not langsmith_configured(settings)):
        return {"status": "skipped", "reason": "LANGSMITH_API_KEY is not set"}
    try:
        if client is None:
            if settings is None:
                raise ValueError("no settings for LangSmith")
            client = make_client(settings)
        dataset_id, examples = upload_dataset(client, base_name, cases, expected)
        project = f"eval-{experiment}-{str(run_id)[:8]}"
        log_experiment(client, project, examples, results, metadata)
        return {
            "status": "uploaded",
            "dataset": dataset_name(base_name, cases),
            "dataset_id": dataset_id,
            "project": project,
        }
    except Exception as exc:  # LangSmith problems must not fail the evaluation
        logger.warning("LangSmith upload failed: %s", exc)
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"[:300]}
