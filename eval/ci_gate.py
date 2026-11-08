"""CI live evaluation gate (Step 23, docs/ci.md).

    python -m eval.ci_gate

Runs the ``ci.cases`` subset of config/eval.yaml through the real agent with the pinned
model, then fails (exit 1) if any unsafe case executed SQL, any case leaked data, or the
answerable cases' accuracy is below ``ci.min_accuracy``. Exits 2 when LLM_API_KEY is not
set (the workflow skips this job before that happens). Results are stored like any run
(experiment ``ci-<git sha>``); nothing is uploaded to LangSmith.
"""

import asyncio
import os
import sys

from app.agent.deps import default_deps
from app.core.config import get_settings
from app.db.session import create_app_engine, create_session_factory
from app.eval.gate import check_gate
from app.eval.runner import (
    CaseOutcome,
    EvalOptions,
    EvalRunner,
    get_eval_config,
    pinned_llm_factory,
)
from eval.run_eval import PLACEHOLDERS, check_model, llm_key, print_case


async def main_async() -> int:
    settings = get_settings()
    config = get_eval_config()
    if llm_key(settings) in PLACEHOLDERS:
        print("LLM_API_KEY is not set: the live evaluation cannot run.")
        return 2
    problem = check_model(settings, config.model)
    if problem:
        print(f"Pinned model check failed: {problem}")
        return 1
    sha = os.environ.get("GITHUB_SHA", "local")[:8]
    options = EvalOptions(experiment_name=f"ci-{sha}", case_ids=config.ci.cases)
    engine = create_app_engine(settings)
    runner = EvalRunner(
        create_session_factory(engine),
        default_deps,
        config=config,
        make_llm=pinned_llm_factory(settings),
    )
    outcomes: list[CaseOutcome] = []

    def collect(outcome: CaseOutcome) -> None:
        outcomes.append(outcome)
        print_case(outcome)

    run_id = await runner.create_run(options)
    print(f"CI gate run {run_id}: {len(config.ci.cases)} cases, model {config.model}")
    metrics = await runner.execute(run_id, options, on_case=collect)
    await engine.dispose()
    if metrics is None:
        print("The evaluation run itself failed.")
        return 1
    gate = check_gate(outcomes, config.ci.min_accuracy)
    print(
        f"\nanswerable accuracy {gate.accuracy}, unsafe executed {gate.unsafe_executed or 'none'}, "
        f"leaks {gate.leaks or 'none'}"
    )
    if not gate.passed:
        for p in gate.problems:
            print(f"GATE FAILED: {p}")
        return 1
    print("Gate passed: no unsafe query executed, no leak, accuracy at or above the minimum.")
    return 0


def main() -> int:
    return asyncio.run(
        main_async(), loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None
    )


if __name__ == "__main__":
    sys.exit(main())
