"""Shared helpers for N-06 and N-09: render the retrieved context for the prompts."""

from app.agent.state import AgentState
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


def question_text(state: AgentState) -> str:
    parts = [state.question]
    if state.intent is not None and state.intent.summary != state.question:
        parts.append(f"(understood as: {state.intent.summary})")
    answers = [c.answer for c in state.clarifications if c.answer]
    if answers:
        parts.append(f"(clarified: {'; '.join(answers)})")
    return " ".join(parts)
