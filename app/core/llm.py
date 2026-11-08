"""One safe, configurable way for the agent to call the LLM (brief sections 22 and 27).

- ``build_chat_model`` creates the chat model from config/llm.yaml (provider, model,
  temperature, max tokens, timeout). LangChain's own retries are turned off; this module
  owns retries so they follow one policy.
- ``LLMClient.ainvoke`` adds a per-attempt timeout, retries with progressive backoff for
  retryable errors only, and charges every call to the question's ``BudgetTracker``.
- LangSmith tracing is controlled only by the LANGSMITH_* environment variables, which
  LangChain reads itself; nothing here turns it on or off.
"""

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.core.config import PROJECT_ROOT, Settings
from app.core.errors import (
    BudgetExceeded,
    MalformedOutput,
    NonRetryableError,
    RetryableError,
)
from app.core.yaml_config import load_yaml_model

LLM_CONFIG_FILE = PROJECT_ROOT / "config" / "llm.yaml"
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RetryConfig(_Strict):
    max_attempts: int = Field(ge=1, le=10)
    initial_backoff_seconds: float = Field(ge=0)
    backoff_multiplier: float = Field(ge=1)
    max_backoff_seconds: float = Field(ge=0)


class BudgetConfig(_Strict):
    max_tokens_per_question: int = Field(gt=0)
    max_cost_usd_per_question: float = Field(gt=0)


class PricingConfig(_Strict):
    input_per_million_usd: float = Field(ge=0)
    output_per_million_usd: float = Field(ge=0)

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_million_usd + output_tokens * self.output_per_million_usd
        ) / 1_000_000


class LLMConfig(_Strict):
    version: int = Field(ge=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    retry: RetryConfig
    budget: BudgetConfig
    pricing: PricingConfig
    prompts: dict[str, str]


def load_llm_config(path: Path = LLM_CONFIG_FILE) -> LLMConfig:
    return load_yaml_model(path, LLMConfig)


@lru_cache
def get_llm_config() -> LLMConfig:
    return load_llm_config()


def build_chat_model(config: LLMConfig, api_key: SecretStr | None) -> BaseChatModel:
    """Create the provider's chat model from config. Our client does the retries."""
    kwargs: dict[str, Any] = {
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "timeout": int(config.timeout_seconds),
        "max_retries": 0,
    }
    if api_key is not None:
        kwargs["api_key"] = api_key.get_secret_value()
    model: BaseChatModel = init_chat_model(config.model, model_provider=config.provider, **kwargs)
    return model


# --- errors ----------------------------------------------------------------------------------


def _status_code(exc: BaseException) -> int | None:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    for attr in ("status_code", "http_status", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def classify_error(exc: BaseException) -> RetryableError | NonRetryableError:
    """Map a provider exception to the error taxonomy."""
    if isinstance(exc, RetryableError | NonRetryableError):
        return exc
    if isinstance(exc, TimeoutError | asyncio.TimeoutError | httpx.TimeoutException):
        return RetryableError(f"LLM call timed out: {type(exc).__name__}")
    if isinstance(exc, httpx.TransportError | ConnectionError):
        return RetryableError(f"connection problem: {type(exc).__name__}")
    status = _status_code(exc)
    if status is not None:
        detail = f"LLM provider returned HTTP {status}"
        return RetryableError(detail) if status in RETRYABLE_STATUS else NonRetryableError(detail)
    return NonRetryableError(f"{type(exc).__name__}: {exc}")


# --- budget ----------------------------------------------------------------------------------


class LLMCallRecord(_Strict):
    node: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    attempts: int


class BudgetTracker:
    """Tokens and estimated cost for one question, across all of its LLM calls."""

    def __init__(
        self,
        budget: BudgetConfig,
        pricing: PricingConfig,
        *,
        spent_input_tokens: int = 0,
        spent_output_tokens: int = 0,
        spent_cost_usd: float = 0.0,
    ) -> None:
        """``spent_*`` carry usage from earlier nodes of the same question."""
        self.budget = budget
        self.pricing = pricing
        self.calls: list[LLMCallRecord] = []
        self._spent = (spent_input_tokens, spent_output_tokens, spent_cost_usd)

    @property
    def input_tokens(self) -> int:
        return self._spent[0] + sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return self._spent[1] + sum(c.output_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float:
        return self._spent[2] + sum(c.cost_usd for c in self.calls)

    def ensure_affordable(self, estimated_input: int, max_output: int) -> None:
        """Raise BudgetExceeded if a call of this size could exceed the budget."""
        tokens = self.total_tokens + estimated_input + max_output
        cost = self.cost_usd + self.pricing.cost(estimated_input, max_output)
        if tokens > self.budget.max_tokens_per_question:
            raise BudgetExceeded(f"token budget: {tokens} > {self.budget.max_tokens_per_question}")
        if cost > self.budget.max_cost_usd_per_question:
            raise BudgetExceeded(
                f"cost budget: ${cost:.4f} > ${self.budget.max_cost_usd_per_question:.4f}"
            )

    def record(self, call: LLMCallRecord) -> None:
        self.calls.append(call)


def estimate_tokens(messages: Sequence[BaseMessage]) -> int:
    """Rough input size before a call (about 4 characters per token)."""
    chars = sum(len(str(m.content)) for m in messages)
    return chars // 4 + 4 * len(messages)


def _usage(message: AIMessage, fallback_input: int) -> tuple[int, int]:
    usage = message.usage_metadata
    if usage:
        return int(usage["input_tokens"]), int(usage["output_tokens"])
    return fallback_input, len(str(message.content)) // 4


# --- client ----------------------------------------------------------------------------------


class ChatModel(Protocol):
    async def ainvoke(self, input: Sequence[BaseMessage], /) -> BaseMessage: ...


Sleep = Callable[[float], Awaitable[None]]


class LLMClient:
    """Calls the chat model with timeout, retry policy and budget accounting."""

    def __init__(
        self, model: ChatModel, config: LLMConfig, *, sleep: Sleep = asyncio.sleep
    ) -> None:
        self.model = model
        self.config = config
        self._sleep = sleep

    def backoff_seconds(self, attempt: int) -> float:
        """Delay before retry number ``attempt`` (1-based): progressive, capped."""
        retry = self.config.retry
        delay = retry.initial_backoff_seconds * retry.backoff_multiplier ** (attempt - 1)
        return float(min(delay, retry.max_backoff_seconds))

    async def ainvoke(
        self, messages: Sequence[BaseMessage], *, budget: BudgetTracker, node: str
    ) -> AIMessage:
        estimated = estimate_tokens(messages)
        budget.ensure_affordable(estimated, self.config.max_tokens)
        attempts = self.config.retry.max_attempts
        start = time.perf_counter()
        last_error: RetryableError | None = None
        for attempt in range(1, attempts + 1):
            try:
                async with asyncio.timeout(self.config.timeout_seconds):
                    reply = await self.model.ainvoke(messages)
            except Exception as exc:
                error = classify_error(exc)
                if isinstance(error, NonRetryableError):
                    raise error from exc
                last_error = error
                if attempt < attempts:
                    await self._sleep(self.backoff_seconds(attempt))
                continue
            if not isinstance(reply, AIMessage):
                raise NonRetryableError(f"unexpected reply type {type(reply).__name__}")
            input_tokens, output_tokens = _usage(reply, estimated)
            budget.record(
                LLMCallRecord(
                    node=node,
                    model=self.config.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=self.config.pricing.cost(input_tokens, output_tokens),
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    attempts=attempt,
                )
            )
            return reply
        detail = last_error.detail if last_error else "no attempt was made"
        raise RetryableError(f"gave up after {attempts} attempts: {detail}")


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def extract_json(text: str) -> object:
    """Parse a JSON object from a model reply (a surrounding code fence is allowed)."""
    match = _FENCE.match(text)
    body = match.group(1) if match else text.strip()
    if not body.startswith("{"):
        start, end = body.find("{"), body.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in the reply")
        body = body[start : end + 1]
    # strict=False: models often put real line breaks inside strings (multi-line SQL).
    return json.loads(body, strict=False)


class StructuredReply[M: BaseModel](BaseModel):
    model_config = ConfigDict(frozen=True)

    value: M
    regenerations: int


async def ainvoke_structured[M: BaseModel](
    client: "LLMClient",
    messages: Sequence[BaseMessage],
    schema: type[M],
    *,
    budget: BudgetTracker,
    node: str,
    max_regenerations: int = 1,
    check: Callable[[M], None] | None = None,
) -> StructuredReply[M]:
    """Ask for JSON matching ``schema``; on malformed output regenerate (at most
    ``max_regenerations`` times, sending the problem back), then raise MalformedOutput.

    ``check`` may raise ValueError for replies that parse but are not acceptable (for
    example a table outside the allowed context); that counts as malformed too."""
    conversation = list(messages)
    problem = ""
    for attempt in range(max_regenerations + 1):
        reply = await client.ainvoke(conversation, budget=budget, node=node)
        text = str(reply.content)
        try:
            value = schema.model_validate(extract_json(text))
            if check is not None:
                check(value)
            return StructuredReply[M](value=value, regenerations=attempt)
        except (ValueError, ValidationError) as exc:
            problem = str(exc).splitlines()[0][:300]
            conversation = [
                *messages,
                reply,
                HumanMessage(
                    "Your reply was not valid. Problem: "
                    f"{problem}. Reply again with only one JSON object that matches the schema."
                ),
            ]
    raise MalformedOutput(f"{node}: invalid structured output after regeneration: {problem}")


def create_llm_client(settings: Settings, config: LLMConfig | None = None) -> LLMClient:
    """The agent's LLM client: provider model from config, API key from the environment."""
    config = config or get_llm_config()
    return LLMClient(build_chat_model(config, settings.llm_api_key), config)


def new_budget(config: LLMConfig | None = None) -> BudgetTracker:
    """A fresh per-question budget."""
    config = config or get_llm_config()
    return BudgetTracker(config.budget, config.pricing)
