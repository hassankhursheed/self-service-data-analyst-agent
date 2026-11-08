"""Shared helpers for N-06 and N-09: render the retrieved context for the prompts."""

import re

from app.agent.state import AgentState
from app.core.enums import RegionCode
from app.semantic.retriever import RetrievedContext


def schema_text(context: RetrievedContext) -> str:
    lines: list[str] = []
    for table in context.tables:
        lines.append(f"- {table.name}: {table.description}")
        for column in table.columns:
            examples = f" (e.g. {', '.join(column.examples[:3])})" if column.examples else ""
            lines.append(f"    - {column.name}: {column.description}{examples}")
    if context.joins:
        lines.append("Joins:")
        lines.extend(f"- {j.condition}" for j in context.joins)
    return "\n".join(lines)


def metrics_text(context: RetrievedContext) -> str:
    if not context.metrics:
        return "(none needed)"
    lines = []
    for metric in context.metrics:
        join = f"; join {metric.join}" if metric.join else ""
        lines.append(
            f"- {metric.name} = {metric.definition} over {', '.join(metric.tables)}{join}"
            f" ({metric.description})"
        )
    return "\n".join(lines)


def date_range_text(state: AgentState) -> str:
    if state.date_range is None:
        return "no period (the question does not need one)"
    return (
        f"{state.date_range.label} "
        f"(from {state.date_range.from_date.isoformat()} to {state.date_range.to_date.isoformat()})"
    )


# How the model writes each sales region in summaries and assumptions.
_REGION_NAMES: dict[RegionCode, str] = {
    RegionCode.EUROPE: r"europe(?:an)?",
    RegionCode.AMERICAS: r"(?:the )?americas?",
    RegionCode.ROW: r"(?:row|rest[ -]of[ -](?:the[ -])?world)",
}


def _own_region_pattern(region: RegionCode) -> re.Pattern[str]:
    return re.compile(
        r"\s*,?\s*\b(?:in|for|within|of|across|from)?\s*(?:the\s+|their\s+|my\s+)?(?:"
        + _REGION_NAMES[region]
        + r")\s+(?:sales\s+)?region\b",
        re.IGNORECASE,
    )


def without_own_region(text: str, region: RegionCode | None) -> str:
    """Remove "in the EUROPE region" for a user whose data is already limited to EUROPE.

    Found in the Step 26 walk-through: given that phrase, the model wrote its own list of
    European countries (missing UK, Norway, Switzerland). The database applies the region,
    so the SQL prompts never mention it; countries the user names are kept.
    """
    if region is None:
        return text
    return re.sub(r"\s{2,}", " ", _own_region_pattern(region).sub("", text)).strip()


def assumptions_for_sql(state: AgentState) -> list[str]:
    """Assumptions for the SQL prompts, without those about the user's own region."""
    region = state.user.region if state.user else None
    if region is None:
        return list(state.assumptions)
    pattern = _own_region_pattern(region)
    return [a for a in state.assumptions if not pattern.search(a)]


def question_text(state: AgentState) -> str:
    """The question for SQL prompts: the standalone version of a follow-up if there is one."""
    region = state.user.region if state.user else None
    parts = [without_own_region(state.interpreted_question or state.question, region)]
    if state.intent is not None and state.intent.summary != state.question:
        summary = without_own_region(state.intent.summary, region)
        parts.append(f"(understood as: {summary})")
    answers = [c.answer for c in state.clarifications if c.answer]
    if answers:
        parts.append(f"(clarified: {'; '.join(answers)})")
    return " ".join(parts)
