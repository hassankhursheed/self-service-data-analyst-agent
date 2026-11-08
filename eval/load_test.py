"""Load test: many users asking questions at the same time (recommended extra, brief §28).

    python -m eval.load_test                       # 20 users x 3 questions
    python -m eval.load_test --users 20 --questions 5 --llm-latency 1.5 --write

Runs the real API, database, semantic layer, SQL validator, read-only executor, audit
and checkpoints in this process. Only the language model is replaced by a stand-in that
waits ``--llm-latency`` seconds per call (like a real model) and returns a fixed valid
reply, so a run costs no model credits and measures our own stack. The virtual users
share the business demo accounts (logged in once each); per-user and per-address limits
are raised for the run, since 20 users from one machine would otherwise be refused.
The questions and conversations of the run are removed afterwards (``--keep`` keeps them).
``--write`` saves the report to eval/LOAD_TEST.md. Tracing is switched off for the run, so
no load-test traces reach LangSmith.
"""

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import os
import statistics
import sys
import time
import uuid
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import psycopg
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel, ConfigDict

from app.agent.deps import default_deps
from app.api.main import create_app
from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.core.llm import LLMClient, get_llm_config

ACCOUNTS = ("sales.europe", "sales.americas", "sales.other", "finance", "operations")
QUESTIONS = (
    "How many orders were placed?",
    "How many orders do we have in total?",
    "Count all orders",
)
REPORT = PROJECT_ROOT / "eval" / "LOAD_TEST.md"

# Fixed replies of the stand-in model, one per prompt (first words of each prompt).
_REPLIES: dict[str, dict[str, object]] = {
    "You analyse business questions": {
        "summary": "Count orders",
        "metric": None,
        "metric_options": [],
        "time_phrase": None,
        "entities": [],
        "grouping": None,
        "top_n": None,
        "missing": [],
        "assumptions": [],
        "clarifying_question": None,
        "options": [],
    },
    "You write PostgreSQL queries": {
        "sql": "SELECT count(*) AS orders FROM orders",
        "tables_used": ["orders"],
        "metrics_used": [],
        "date_range": None,
        "assumptions": [],
        "confidence": "high",
    },
    "You explain query results": {
        "explanation": "The table shows the number of orders you can see.",
        "sql_description": "Counts orders.",
    },
}


class StandInModel:
    """Waits like a real model, then returns the fixed reply for the prompt."""

    def __init__(self, latency: float) -> None:
        self.latency = latency
        self.calls = 0

    async def ainvoke(self, input: Sequence[BaseMessage], /) -> BaseMessage:
        self.calls += 1
        await asyncio.sleep(self.latency)
        text = " ".join(str(m.content) for m in input[:3])
        for marker, reply in _REPLIES.items():
            if marker in text:
                return AIMessage(
                    content=json.dumps(reply),
                    usage_metadata={
                        "input_tokens": 1500,
                        "output_tokens": 150,
                        "total_tokens": 1650,
                    },
                )
        raise RuntimeError("unexpected prompt")  # e.g. a repair: should not happen here


class Sample(BaseModel):
    model_config = ConfigDict(frozen=True)

    user: int
    account: str
    http_status: int
    status: str
    seconds: float


class LoadReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    users: int
    questions_per_user: int
    llm_latency_s: float
    total: int
    wall_seconds: float
    throughput_per_minute: float
    statuses: dict[str, int]
    p50_s: float
    p95_s: float
    max_s: float
    errors: int


def percentile(values: Sequence[float], share: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * share
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarise(
    samples: Sequence[Sample], users: int, per_user: int, latency: float, wall: float
) -> LoadReport:
    seconds = [s.seconds for s in samples]
    return LoadReport(
        users=users,
        questions_per_user=per_user,
        llm_latency_s=latency,
        total=len(samples),
        wall_seconds=round(wall, 2),
        throughput_per_minute=round(len(samples) / wall * 60, 1) if wall else 0.0,
        statuses=dict(Counter(s.status for s in samples)),
        p50_s=round(statistics.median(seconds), 2) if seconds else 0.0,
        p95_s=round(percentile(seconds, 0.95), 2),
        max_s=round(max(seconds), 2) if seconds else 0.0,
        errors=sum(1 for s in samples if s.http_status != 200),
    )


def markdown(report: LoadReport, when: dt.datetime) -> str:
    statuses = ", ".join(f"{k} {v}" for k, v in sorted(report.statuses.items()))
    return "\n".join([
        "# Load test",
        "",
        f"Run {when:%Y-%m-%d %H:%M} UTC with `python -m eval.load_test` (brief §28). Real API,",
        "database, validator, executor, audit and checkpoints; the model is a stand-in",
        f"that waits {report.llm_latency_s} s per call (3 calls per question), so the numbers",
        "show our own stack plus a typical model wait, without spending credits.",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Concurrent users | {report.users} |",
        f"| Questions | {report.total} ({report.questions_per_user} per user) |",
        f"| Outcomes | {statuses} |",
        f"| HTTP errors | {report.errors} |",
        f"| Latency p50 / p95 / max | {report.p50_s} s / {report.p95_s} s / {report.max_s} s |",
        f"| Wall time | {report.wall_seconds} s |",
        f"| Throughput | {report.throughput_per_minute} questions per minute |",
        "",
        "The first runs found three problems under load, fixed in Step 26",
        "(docs/decisions-log.md): parallel first use of the lookup pools (7 of 60 failed, 30 s",
        "waits), driver UUIDs the checkpoint could not restore, and checkpoint saves after every",
        "node behind the Postgres saver's single lock (p50 27 s; 44 questions per minute).",
        "",
    ])  # fmt: skip


def load_settings(settings: Settings) -> Settings:
    """Limits raised for the run: all virtual users come from one machine."""
    limits = settings.api.rate_limits.model_copy(
        update={"questions_per_minute": 10_000, "logins_per_minute_per_ip": 10_000}
    )
    api = settings.api.model_copy(update={"rate_limits": limits, "daily_cost_cap_usd": 0.0})
    alerts = settings.alerts.model_copy(update={"enabled": False})
    return settings.model_copy(update={"api": api, "alerts": alerts})


async def run_load(
    settings: Settings, users: int, per_user: int, latency: float
) -> tuple[LoadReport, list[str]]:
    model = StandInModel(latency)
    base = default_deps()
    deps = dataclasses.replace(base, llm=LLMClient(model, get_llm_config()), trace_client=None)
    app = create_app(load_settings(settings), agent_deps=deps)
    samples: list[Sample] = []
    conversations: list[str] = []
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://load", timeout=120) as client:
            tokens: dict[str, str] = {}
            for account in ACCOUNTS:
                secret = settings.demo_password(account)
                if secret is None:
                    raise SystemExit(f"DEMO_PASSWORD for {account} is not set")
                response = await client.post(
                    "/auth/login",
                    json={"username": account, "password": secret.get_secret_value()},
                )
                response.raise_for_status()
                tokens[account] = response.json()["access_token"]

            async def user(index: int) -> None:
                account = ACCOUNTS[index % len(ACCOUNTS)]
                headers = {"Authorization": f"Bearer {tokens[account]}"}
                for n in range(per_user):
                    started = time.perf_counter()
                    response = await client.post(
                        "/ask", json={"question": QUESTIONS[n % len(QUESTIONS)]}, headers=headers
                    )
                    body = response.json()
                    if "conversation_id" in body:
                        conversations.append(body["conversation_id"])
                    samples.append(
                        Sample(
                            user=index,
                            account=account,
                            http_status=response.status_code,
                            status=str(body.get("status") or body.get("error", {}).get("code")),
                            seconds=time.perf_counter() - started,
                        )
                    )

            started = time.perf_counter()
            await asyncio.gather(*(user(i) for i in range(users)))
            wall = time.perf_counter() - started
    return summarise(samples, users, per_user, latency, wall), conversations


def remove_conversations(settings: Settings, ids: Sequence[str]) -> int:
    if not ids:
        return 0
    with psycopg.connect(settings.owner_conninfo()) as conn:
        cursor = conn.execute(
            "DELETE FROM app.conversations WHERE id = ANY(%s)",
            ([uuid.UUID(i) for i in set(ids)],),
        )
        conn.commit()
        return cursor.rowcount


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--questions", type=int, default=3, help="questions per user")
    parser.add_argument("--llm-latency", type=float, default=1.0, help="seconds per model call")
    parser.add_argument("--write", action="store_true", help=f"save the report to {REPORT.name}")
    parser.add_argument("--keep", action="store_true", help="keep the run's conversations")
    args = parser.parse_args()
    os.environ["LANGSMITH_TRACING"] = "false"  # never trace load-test runs
    get_settings.cache_clear()
    settings = get_settings().model_copy(update={"langsmith_tracing": False})
    if sys.platform == "win32":
        report, ids = asyncio.run(
            run_load(settings, args.users, args.questions, args.llm_latency),
            loop_factory=asyncio.SelectorEventLoop,
        )
    else:
        report, ids = asyncio.run(run_load(settings, args.users, args.questions, args.llm_latency))
    text = markdown(report, dt.datetime.now(dt.UTC))
    print(text)
    if not args.keep:
        print(f"Removed {remove_conversations(settings, ids)} load-test conversations.")
    if args.write:
        Path(REPORT).write_text(text, "utf-8")
        print(f"Saved {REPORT.relative_to(PROJECT_ROOT)}")
    return 0 if report.errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
