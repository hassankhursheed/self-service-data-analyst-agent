"""Step 10: LLM client, retries, timeouts, budgets and prompts (LLM always mocked)."""

import asyncio
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import SecretStr

from app.core.errors import (
    AppError,
    BudgetExceeded,
    DbTimeout,
    NonRetryableError,
    RetryableError,
    ValidationBlocked,
)
from app.core.llm import (
    BudgetTracker,
    LLMClient,
    LLMConfig,
    build_chat_model,
    classify_error,
    load_llm_config,
)
from app.core.prompts import load_prompt
from app.core.yaml_config import ConfigFileError

CONFIG = load_llm_config()
QUESTION = [HumanMessage("How many orders were placed in 2024?")]


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.example.test/v1/chat")
    return httpx.HTTPStatusError(
        f"HTTP {status}", request=request, response=httpx.Response(status, request=request)
    )


def _reply(text: str = "42", tokens_in: int = 100, tokens_out: int = 20) -> AIMessage:
    return AIMessage(
        content=text,
        usage_metadata={
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
        },
    )


class FakeModel:
    """Plays back a script: exceptions are raised, messages are returned."""

    def __init__(self, *script: BaseException | BaseMessage, delay: float = 0.0) -> None:
        self.script = list(script)
        self.calls = 0
        self.delay = delay

    async def ainvoke(self, input: Sequence[BaseMessage], /) -> BaseMessage:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _client(model: FakeModel, config: LLMConfig = CONFIG) -> tuple[LLMClient, Sleeps]:
    sleeps = Sleeps()
    return LLMClient(model, config, sleep=sleeps), sleeps


def _budget(config: LLMConfig = CONFIG) -> BudgetTracker:
    return BudgetTracker(config.budget, config.pricing)


def _config(**changes: object) -> LLMConfig:
    data = CONFIG.model_dump()
    for key, value in changes.items():
        section, _, field = key.partition("__")
        if field:
            data[section][field] = value
        else:
            data[key] = value
    return LLMConfig.model_validate(data)


# --- config and factory ------------------------------------------------------------------


def test_llm_config_loads_from_yaml() -> None:
    assert CONFIG.provider == "mistralai"
    assert CONFIG.temperature == 0
    assert CONFIG.retry.max_attempts >= 2


def test_factory_builds_the_configured_model_without_its_own_retries() -> None:
    model = build_chat_model(CONFIG, SecretStr("test-key-not-real"))
    assert type(model).__name__ == "ChatMistralAI"
    assert getattr(model, "model", None) == CONFIG.model
    assert getattr(model, "temperature", None) == CONFIG.temperature
    assert getattr(model, "max_tokens", None) == CONFIG.max_tokens
    assert getattr(model, "timeout", None) == int(CONFIG.timeout_seconds)
    assert getattr(model, "max_retries", None) == 0


# --- retries -------------------------------------------------------------------------------


async def test_retryable_error_succeeds_on_the_second_attempt() -> None:
    model = FakeModel(_http_error(503), _reply("ok"))
    client, sleeps = _client(model)
    budget = _budget()
    reply = await client.ainvoke(QUESTION, budget=budget, node="N-06")
    assert reply.content == "ok"
    assert model.calls == 2
    assert sleeps.delays == [CONFIG.retry.initial_backoff_seconds]
    assert budget.calls[0].attempts == 2


@pytest.mark.parametrize(
    "error",
    [
        _http_error(429),
        _http_error(500),
        _http_error(502),
        httpx.ConnectError("down"),
        TimeoutError(),
    ],
)
def test_retryable_errors_are_classified_as_retryable(error: BaseException) -> None:
    assert isinstance(classify_error(error), RetryableError)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_non_retryable_error_is_not_retried(status: int) -> None:
    model = FakeModel(_http_error(status), _reply())
    client, sleeps = _client(model)
    with pytest.raises(NonRetryableError, match=str(status)):
        await client.ainvoke(QUESTION, budget=_budget(), node="N-06")
    assert model.calls == 1
    assert sleeps.delays == []


async def test_gives_up_after_max_attempts_with_progressive_backoff() -> None:
    config = _config(retry__max_attempts=4, retry__max_backoff_seconds=3.0)
    model = FakeModel(*[_http_error(503)] * 4)
    client, sleeps = _client(model, config)
    with pytest.raises(RetryableError, match="gave up after 4 attempts"):
        await client.ainvoke(QUESTION, budget=_budget(config), node="N-06")
    assert model.calls == 4
    assert sleeps.delays == [1.0, 2.0, 3.0]  # 1, 2, then capped at 3


def test_unknown_exception_is_not_retried() -> None:
    assert isinstance(classify_error(ValueError("bad prompt")), NonRetryableError)


# --- timeout -------------------------------------------------------------------------------


async def test_timeout_is_applied_to_each_attempt() -> None:
    config = _config(timeout_seconds=0.05, retry__max_attempts=2)
    model = FakeModel(_reply(), _reply(), delay=0.5)
    client, sleeps = _client(model, config)
    with pytest.raises(RetryableError, match="timed out"):
        await client.ainvoke(QUESTION, budget=_budget(config), node="N-06")
    assert model.calls == 2
    assert len(sleeps.delays) == 1


async def test_slow_first_attempt_then_fast_success() -> None:
    config = _config(timeout_seconds=0.05)

    class SlowThenFast(FakeModel):
        async def ainvoke(self, input: Sequence[BaseMessage], /) -> BaseMessage:
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(0.5)
            return _reply("fast")

    model = SlowThenFast()
    client, _ = _client(model, config)
    reply = await client.ainvoke(QUESTION, budget=_budget(config), node="N-06")
    assert reply.content == "fast"


# --- budget --------------------------------------------------------------------------------


async def test_tokens_and_cost_are_recorded_per_call() -> None:
    model = FakeModel(_reply(tokens_in=1000, tokens_out=200), _reply(tokens_in=500, tokens_out=50))
    client, _ = _client(model)
    budget = _budget()
    await client.ainvoke(QUESTION, budget=budget, node="N-03")
    await client.ainvoke(QUESTION, budget=budget, node="N-06")
    assert [c.node for c in budget.calls] == ["N-03", "N-06"]
    assert (budget.input_tokens, budget.output_tokens) == (1500, 250)
    expected = (
        1500 * CONFIG.pricing.input_per_million_usd + 250 * CONFIG.pricing.output_per_million_usd
    ) / 1e6
    assert budget.cost_usd == pytest.approx(expected)


async def test_budget_stops_a_call_that_would_exceed_it() -> None:
    config = _config(budget__max_tokens_per_question=2500, max_tokens=1000)
    model = FakeModel(_reply(tokens_in=1500, tokens_out=300), _reply())
    client, _ = _client(model, config)
    budget = _budget(config)
    await client.ainvoke(QUESTION, budget=budget, node="N-06")  # 1800 used
    with pytest.raises(BudgetExceeded, match="token budget"):
        await client.ainvoke(
            QUESTION, budget=budget, node="N-09"
        )  # 1800 used + ~13 input + 1000 max output > 2500
    assert model.calls == 1  # the second call never reached the model


async def test_cost_budget_is_enforced_too() -> None:
    config = _config(budget__max_cost_usd_per_question=0.000001)
    model = FakeModel(_reply())
    client, _ = _client(model, config)
    with pytest.raises(BudgetExceeded, match="cost budget"):
        await client.ainvoke(QUESTION, budget=_budget(config), node="N-06")
    assert model.calls == 0


async def test_missing_usage_metadata_falls_back_to_an_estimate() -> None:
    model = FakeModel(AIMessage(content="x" * 400))
    client, _ = _client(model)
    budget = _budget()
    await client.ainvoke(QUESTION, budget=budget, node="N-10")
    assert budget.output_tokens == 100
    assert budget.input_tokens > 0


# --- errors --------------------------------------------------------------------------------


def test_error_taxonomy_has_codes_and_safe_messages() -> None:
    from app.core.enums import BlockReason

    errors: list[AppError] = [
        RetryableError("x"),
        NonRetryableError("x"),
        BudgetExceeded("x"),
        DbTimeout("x"),
        ValidationBlocked(BlockReason.WRITE_STATEMENT, user_message="Not allowed."),
    ]
    assert len({e.code for e in errors}) == len(errors)
    assert all(e.user_message for e in errors)
    assert errors[-1].user_message == "Not allowed."


# --- prompts -------------------------------------------------------------------------------


def test_every_configured_prompt_loads_by_name_and_version() -> None:
    for name, version in CONFIG.prompts.items():
        prompt = load_prompt(name, version)
        assert prompt.ref == f"{name}@{version}"
        messages = prompt.to_chat_prompt().format_messages(
            **dict.fromkeys(prompt.input_variables, "test")
        )
        assert messages


def test_system_prompt_uses_the_business_date() -> None:
    prompt = load_prompt("system", "v1")
    text = prompt.to_chat_prompt().format_messages(business_today="2025-05-06")[0].content
    assert "2025-05-06" in str(text)


def _write_prompt(tmp_path: Path, body: str, name: str = "demo", version: str = "v1") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    (folder / f"{version}.yaml").write_text(body, "utf-8")
    return tmp_path


def test_prompt_with_undeclared_variable_fails(tmp_path: Path) -> None:
    root = _write_prompt(
        tmp_path,
        "name: demo\nversion: v1\ndescription: d\ninput_variables: []\n"
        "messages:\n  - role: human\n    content: 'Hello {who}'\n",
    )
    with pytest.raises(ConfigFileError, match="do not match"):
        load_prompt("demo", "v1", root)


def test_prompt_file_must_match_its_name_and_version(tmp_path: Path) -> None:
    root = _write_prompt(
        tmp_path,
        "name: other\nversion: v1\ndescription: d\ninput_variables: []\n"
        "messages:\n  - role: system\n    content: hi\n",
    )
    with pytest.raises(ConfigFileError, match="expected demo@v1"):
        load_prompt("demo", "v1", root)


def test_missing_prompt_version_fails_clearly() -> None:
    with pytest.raises(ConfigFileError, match="file not found"):
        load_prompt("system", "v99")


def test_json_replies_may_contain_line_breaks_inside_strings() -> None:
    """Found by the evaluation: models write multi-line SQL inside the JSON string."""
    from app.core.llm import extract_json

    # A real line break inside the JSON string value: not valid strict JSON.
    reply = '```json\n{"sql": "SELECT count(*)\nFROM orders o", "tables_used": ["orders"]}\n```'
    value = extract_json(reply)
    assert isinstance(value, dict)
    assert value["sql"] == "SELECT count(*)\nFROM orders o"
