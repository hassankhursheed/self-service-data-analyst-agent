"""Build the results tables of eval/RESULTS.md from stored runs (Step 22).

    python -m eval.report RUN_ID [RUN_ID ...]

Prints the Markdown for a comparison table (one column per run), the settings recorded
with each run, and the failing cases of every run. The numbers come straight from
eval_runs and eval_results; nothing is typed by hand.
"""

import asyncio
import sys
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import EvalCase, EvalResult, EvalRun
from app.db.session import create_app_engine, create_session_factory
from app.eval.runner import get_eval_config


def pct(value: Decimal | None) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"


async def build(run_ids: list[uuid.UUID]) -> str:
    engine = create_app_engine(get_settings())
    sessions = create_session_factory(engine)
    targets = get_eval_config().targets
    lines: list[str] = []
    async with sessions() as session:
        runs = [r for i in run_ids if (r := await session.get(EvalRun, i)) is not None]
        header = "| Metric | Target | " + " | ".join(r.experiment_name for r in runs) + " |"
        lines += [header, "|" + " --- |" * (len(runs) + 2)]

        def row(label: str, target: str, values: list[str]) -> None:
            lines.append(f"| {label} | {target} | " + " | ".join(values) + " |")

        row(
            "Execution accuracy",
            f"{targets.execution_accuracy:.0%}+",
            [pct(r.execution_accuracy) for r in runs],
        )
        row(
            "Clarification rate (ambiguous)",
            f"{targets.clarification_rate:.0%}+",
            [pct(r.clarification_rate) for r in runs],
        )
        row(
            "Unsafe queries blocked",
            f"{targets.unsafe_blocked_rate:.0%}",
            [pct(r.unsafe_blocked_rate) for r in runs],
        )
        row("Access-control leaks", str(targets.access_leaks), [str(r.access_leaks) for r in runs])
        row(
            "Answers with ungrounded numbers",
            str(targets.ungrounded_answers),
            [str(r.ungrounded_answers) for r in runs],
        )
        row(
            "Latency p50 / p95",
            "report",
            [f"{r.latency_p50_ms} / {r.latency_p95_ms} ms" for r in runs],
        )
        row("Average cost per question", "report", [f"${r.avg_cost_usd}" for r in runs])
        row("Cases passed", "—", [f"{r.cases_passed} / {r.cases_total}" for r in runs])
        lines += ["", "Settings recorded with each run:", ""]
        for r in runs:
            s = r.settings
            lines.append(
                f"- **{r.experiment_name}** (`{r.id}`): model `{r.model_name}`, temperature "
                f"{r.temperature}, reference date {r.reference_date}, graph {r.graph_version}, "
                f"semantic `{r.semantic_version}`, verified examples "
                f"{'on' if r.verified_examples_enabled else 'off'} (library "
                f"{s.get('verified_library')}), cases v{s.get('cases_version')}, prompts "
                f"`{r.prompt_version}`, LangSmith {s.get('langsmith', {}).get('status', 'n/a')}."
            )
        for r in runs:
            failing = (
                await session.execute(
                    select(EvalCase.case_key, EvalResult.final_status, EvalResult.failure_reason)
                    .join(EvalCase, EvalCase.id == EvalResult.case_id)
                    .where(EvalResult.run_id == r.id, EvalResult.passed.is_(False))
                    .order_by(EvalCase.case_key)
                )
            ).all()
            lines += ["", f"Failing cases in **{r.experiment_name}** ({len(failing)}):", ""]
            lines += [f"- {key}: {status or '-'}: {reason}" for key, status, reason in failing]
    await engine.dispose()
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ids = [uuid.UUID(a) for a in sys.argv[1:]]
    print(asyncio.run(build(ids), loop_factory=asyncio.SelectorEventLoop))
    return 0


if __name__ == "__main__":
    sys.exit(main())
