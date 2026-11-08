"""Intent analysis model (LLM output) and the deterministic continue / assume / ask decision.

The LLM only describes the question. This module decides, with fixed rules from
config/agent.yaml, whether the agent continues, continues with a stated assumption, or
asks one clarifying question (brief section 14). Time phrases are resolved with the
business calendar (Step 8), never the real date.
"""

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.config import IntentConfig, IntentPart
from app.semantic.calendar import (
    CalendarConfig,
    DateRange,
    UnresolvedPeriod,
    find_period,
    resolve_period,
)


class MissingPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    part: IntentPart
    reason: str = ""


class IntentAnalysis(BaseModel):
    """Structured output of the intent prompt (config/prompts/intent)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1)
    metric: str | None = None
    metric_options: list[str] = []
    time_phrase: str | None = None
    entities: list[str] = []
    grouping: str | None = None
    top_n: int | None = Field(default=None, ge=1, le=1000)
    missing: list[MissingPart] = []
    assumptions: list[str] = []
    clarifying_question: str | None = None
    options: list[str] = Field(default=[], max_length=6)
    # Follow-ups (Step 15): the question rewritten to stand on its own.
    is_follow_up: bool = False
    standalone_question: str | None = None

    @field_validator(
        "metric_options", "entities", "missing", "assumptions", "options", mode="before"
    )
    @classmethod
    def _null_is_empty(cls, value: object) -> object:
        """Some models write null for an empty list; both mean "nothing" (Step 22)."""
        return [] if value is None else value

    @field_validator(
        "time_phrase", "metric", "grouping", "clarifying_question", "standalone_question"
    )
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if isinstance(value, str) else value


class IntentOutcome(StrEnum):
    CLEAR = "clear"
    ASSUMED = "assumed"
    AMBIGUOUS = "ambiguous"
    UNCLEAR_AFTER_CLARIFICATION = "unclear_after_clarification"


class ClarificationDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str
    options: list[str] = Field(min_length=2, max_length=4)
    missing_parts: list[IntentPart]


class IntentDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: IntentOutcome
    date_range: DateRange | None = None
    assumptions: list[str] = []
    missing_parts: list[IntentPart] = []
    clarification: ClarificationDraft | None = None
    top_n: int | None = None


_PART_ORDER: list[IntentPart] = ["metric", "entity", "grouping", "time_range", "top_n"]


def _readable(metric: str) -> str:
    return metric.replace("_", " ")


def template_clarification(
    parts: list[IntentPart], metric_options: list[str], config: IntentConfig
) -> ClarificationDraft:
    """A deterministic question when the model's own question is missing or unusable."""
    phrases: list[str] = []
    metrics = (metric_options or config.fallback_metric_options)[:2]
    if "metric" in parts:
        phrases.append("by " + " or by ".join(_readable(m) for m in metrics))
    if "entity" in parts:
        phrases.append("for which customer, product or country")
    if "grouping" in parts:
        phrases.append("grouped by what (for example customer, product or month)")
    if "time_range" in parts:
        phrases.append("for which year or period")
    if "top_n" in parts:
        phrases.append("how many results")
    question = "Do you mean " + ", and ".join(phrases) + "?" if phrases else "Could you clarify?"
    periods = ["last year", "this year"] if "time_range" in parts else [""]
    options = [
        f"By {_readable(m)}{', ' + p if p else ''}" for m in metrics for p in periods
    ] if "metric" in parts else [p.capitalize() for p in ["last year", "this year"]]  # fmt: skip
    return ClarificationDraft(question=question, options=options[:4], missing_parts=parts)


def merge_assumptions(*groups: Sequence[str]) -> list[str]:
    """All assumptions in order, each once (ignoring case, spaces and a final full stop);
    the model often repeats the ones it was given (Step 26 walk-through)."""
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for text in group:
            key = " ".join(text.lower().split()).rstrip(".")
            if key and key not in seen:
                seen.add(key)
                merged.append(text)
    return merged


def decide(
    analysis: IntentAnalysis,
    calendar: CalendarConfig,
    config: IntentConfig,
    *,
    rounds_asked: int = 0,
    texts: Sequence[str | None] = (),
) -> IntentDecision:
    """Continue, continue with assumptions, or ask (at most ``max_clarification_rounds``).

    ``texts`` (the standalone follow-up question, then the question) are searched for a
    period when the model returned none it could resolve."""
    missing: set[IntentPart] = {m.part for m in analysis.missing}
    assumptions = list(analysis.assumptions)
    date_range: DateRange | None = None

    if analysis.time_phrase:
        resolved = resolve_period(analysis.time_phrase, calendar)
        if isinstance(resolved, UnresolvedPeriod):
            missing.add("time_range")
        else:
            date_range = resolved
            missing.discard("time_range")
            if resolved.assumption:
                assumptions.append(resolved.assumption)
    if date_range is None:
        for text in texts:
            found = find_period(text, calendar) if text else None
            if found is not None:
                date_range = found
                missing.discard("time_range")
                if found.assumption:
                    assumptions.append(found.assumption)
                break

    blocking = missing & set(config.blocking_parts)
    if blocking:
        parts = [p for p in _PART_ORDER if p in missing]
        if rounds_asked >= config.max_clarification_rounds:
            return IntentDecision(
                outcome=IntentOutcome.UNCLEAR_AFTER_CLARIFICATION, missing_parts=parts
            )
        draft = _model_clarification(analysis, parts) or template_clarification(
            parts, analysis.metric_options, config
        )
        return IntentDecision(
            outcome=IntentOutcome.AMBIGUOUS, missing_parts=parts, clarification=draft
        )

    if "time_range" in missing and date_range is None:
        default = resolve_period(config.default_period, calendar)
        if isinstance(default, DateRange):
            date_range = default
            assumptions.append(f"No time period given: assumed {default.label}.")
    top_n = analysis.top_n
    if "top_n" in missing and top_n is None:
        top_n = config.default_top_n
        assumptions.append(f"No number given: assumed the top {top_n}.")
    return IntentDecision(
        outcome=IntentOutcome.ASSUMED if assumptions else IntentOutcome.CLEAR,
        date_range=date_range,
        assumptions=assumptions,
        missing_parts=sorted(missing),
        top_n=top_n,
    )


def _model_clarification(
    analysis: IntentAnalysis, parts: list[IntentPart]
) -> ClarificationDraft | None:
    """Use the model's own question when it is usable (one question, 2-4 options)."""
    options = [o.strip() for o in analysis.options if o.strip()]
    if not analysis.clarifying_question or not 2 <= len(options) <= 4:
        return None
    return ClarificationDraft(
        question=analysis.clarifying_question, options=options, missing_parts=parts
    )
