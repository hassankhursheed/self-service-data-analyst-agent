"""Run the evaluation set through the real agent (Step 22, docs/evaluation.md).

    python -m eval.run_eval --experiment with-verified-examples
    python -m eval.run_eval --experiment without-verified-examples --no-verified
    python -m eval.run_eval --experiment names-only-semantic --no-verified --semantic names_only
    python -m eval.run_eval --experiment smoke --cases S-01,U-01

Every case runs as its test user through the read-only role with the fixed settings of
config/eval.yaml (pinned model version, temperature 0). Results go to eval_runs /
eval_results and, when LANGSMITH_API_KEY is set, to LangSmith. Needs LLM_API_KEY.
"""

import argparse
import asyncio
import sys

import httpx

from app.agent.deps import default_deps
from app.core.config import Settings, get_settings
from app.core.enums import CaseType
from app.core.llm import get_llm_config
from app.db.session import create_app_engine, create_session_factory
from app.eval.langsmith_sync import langsmith_configured
from app.eval.runner import (
    CaseOutcome,
    EvalOptions,
    EvalRunner,
    get_eval_config,
    pinned_llm_factory,
)

PLACEHOLDERS = {"", "CHANGE_ME"}


def llm_key(settings: Settings) -> str:
    return settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""


def check_model(settings: Settings, model: str) -> str | None:
    """Return an error message when the pinned Mistral model is not offered (None if ok)."""
    response = httpx.get(
        "https://api.mistral.ai/v1/models",
        headers={"Authorization": f"Bearer {llm_key(settings)}"},
        timeout=20,
    )
    if response.status_code == 401:
        return "LLM_API_KEY was refused by the provider (401)."
    response.raise_for_status()
    ids = {m["id"] for m in response.json().get("data", [])}
    if model in ids:
        return None
    small = sorted(i for i in ids if "small" in i)
    return f"model {model!r} is not offered; dated small models available: {small}"


def print_case(outcome: CaseOutcome) -> None:
    mark = "PASS" if outcome.passed else "FAIL"
    extra = " LEAK" if outcome.score.leaked else ""
    extra += " UNGROUNDED" if outcome.score.ungrounded else ""
    print(
        f"  {outcome.case.id}  {mark}{extra}  {outcome.status or '-':<22} "
        f"{outcome.latency_ms:>6} ms  {outcome.score.reason}"
    )


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    config = get_eval_config()
    if llm_key(settings) in PLACEHOLDERS:
        print("LLM_API_KEY is not set in .env; the evaluation needs the real model.")
        return 2
    if not args.skip_model_check and get_llm_config().provider == "mistralai":
        problem = check_model(settings, config.model)
        if problem:
            print(f"Pinned model check failed: {problem}")
            return 2
    options = EvalOptions(
        experiment_name=args.experiment,
        verified_examples_enabled=not args.no_verified,
        semantic_mode=args.semantic,
        case_ids=args.cases.split(",") if args.cases else None,
        case_types=[CaseType(t) for t in args.types.split(",")] if args.types else None,
    )
    engine = create_app_engine(settings)
    runner = EvalRunner(
        create_session_factory(engine),
        default_deps,
        config=config,
        make_llm=pinned_llm_factory(settings),
        settings=settings,
    )
    run_id = await runner.create_run(options)
    print(
        f"run {run_id}  experiment={options.experiment_name}  model={config.model}  "
        f"verified_examples={options.verified_examples_enabled}  semantic={options.semantic_mode}"
        f"  langsmith={'on' if langsmith_configured(settings) else 'off'}"
    )
    metrics = await runner.execute(run_id, options, on_case=print_case)
    await engine.dispose()
    if metrics is None:
        print("The run failed; see eval_runs.error_message.")
        return 1
    t = config.targets
    print("\nResults (target in brackets)")
    print(f"  execution accuracy   {metrics.execution_accuracy}  [{t.execution_accuracy}+]")
    print(f"  clarification rate   {metrics.clarification_rate}  [{t.clarification_rate}+]")
    print(f"  unsafe blocked       {metrics.unsafe_blocked_rate}  [{t.unsafe_blocked_rate}]")
    print(f"  access-control pass  {metrics.access_control_pass_rate}")
    print(f"  access leaks         {metrics.access_leaks}  [{t.access_leaks}]")
    print(f"  ungrounded answers   {metrics.ungrounded_answers}  [{t.ungrounded_answers}]")
    print(f"  latency p50 / p95    {metrics.latency_p50_ms} / {metrics.latency_p95_ms} ms")
    print(f"  avg cost / question  ${metrics.avg_cost_usd}")
    print(f"  passed               {metrics.cases_passed} / {metrics.cases_total}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--experiment", required=True, help="name shown in the results")
    parser.add_argument("--no-verified", action="store_true", help="turn verified examples off")
    parser.add_argument("--semantic", choices=["full", "names_only"], default="full")
    parser.add_argument("--cases", help="comma-separated case IDs (default: all)")
    parser.add_argument("--types", help="comma-separated case types (default: all)")
    parser.add_argument("--skip-model-check", action="store_true")
    args = parser.parse_args()
    return asyncio.run(main_async(args), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    sys.exit(main())
