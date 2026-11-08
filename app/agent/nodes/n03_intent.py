"""N-03 Intent and Ambiguity: LLM analysis (structured output) plus a fixed decision rule."""

from app.agent.deps import AgentDeps, usage_of
from app.agent.intent import IntentAnalysis, IntentOutcome, decide
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.state import AgentErrorInfo, AgentState
from app.core.enums import NodeName, QuestionStatus, RegionCode, RoleName
from app.core.errors import AppError
from app.core.llm import ainvoke_structured
from app.core.prompts import load_prompt
from app.semantic.models import SemanticLayer

S = QuestionStatus
UNCLEAR_MESSAGE = (
    "I still couldn't tell exactly what you need. Please ask again and include the measure "
    "(for example revenue or number of orders) and the period."
)


def _metrics_text(layer: SemanticLayer, role: RoleName) -> str:
    lines = [
        f"- {name}: {m.description}" + (f" (also: {', '.join(m.synonyms)})" if m.synonyms else "")
        for name, m in layer.metrics.items()
        if role in m.allowed_roles
    ]
    return "\n".join(lines) or "- (none)"


def _tables_text(layer: SemanticLayer, role: RoleName) -> str:
    return ", ".join(t for t, d in layer.tables.items() if role in d.allowed_roles)


def _clarifications_text(state: AgentState) -> str:
    answered = [c for c in state.clarifications if c.answer is not None]
    if not answered:
        return "none"
    return " | ".join(f"Asked: {c.question} Answer: {c.answer}" for c in answered)


def _history_text(state: AgentState) -> str:
    if not state.history:
        return "none (this is the first question)"
    lines = []
    for i, turn in enumerate(state.history, 1):
        period = f"; period: {turn.date_range_label}" if turn.date_range_label else ""
        lines.append(f"{i}. {turn.interpreted_question}{period}")
    return "\n".join(lines)


def _interpreted(state: AgentState, analysis: IntentAnalysis) -> str | None:
    """The standalone question for a follow-up; None when the question stands on its own."""
    if not state.history or not analysis.is_follow_up or not analysis.standalone_question:
        return None
    if analysis.standalone_question.strip().lower() == state.question.strip().lower():
        return None
    return analysis.standalone_question


def _with_interpretation(notices: list[str], question: str, interpreted: str | None) -> list[str]:
    kept = [n for n in notices if not n.startswith("Interpreted as: ")]
    return [*kept, f"Interpreted as: {interpreted}"] if interpreted else kept


def user_scope(role: RoleName, region: RegionCode | None) -> str:
    """Who is asking, for the intent prompt (v3): role and the data they can see."""
    label = role.value.replace("_", " ")
    if region is not None:
        return (
            f"a {label} for the {region.value} sales region; their data is already "
            f"limited to that region, so 'my region' means {region.value}."
        )
    return f"a {label}; they see the data of all regions."


def make_intent_node(deps: AgentDeps) -> NodeFn:
    @agent_node(NodeName.INTENT)
    async def intent_and_ambiguity(state: AgentState) -> NodeUpdate:
        if state.user is None:
            raise AppError("intent reached without a user context")
        prompt = load_prompt("intent", deps.llm_config.prompts["intent"])
        layer = await deps.load_semantic()
        values = {
            "business_today": deps.calendar.reference_date.isoformat(),
            "user_scope": user_scope(state.user.role, state.user.region),
            "metrics": _metrics_text(layer, state.user.role),
            "tables": _tables_text(layer, state.user.role),
            "history": _history_text(state),
            "question": state.question,
            "clarifications": _clarifications_text(state),
        }
        messages = [
            *deps.system_messages(),
            *prompt.to_chat_prompt().format_messages(
                **{k: v for k, v in values.items() if k in prompt.input_variables}
            ),
        ]
        budget = deps.budget_for(state)
        config = deps.agent_config.intent
        try:
            reply = await ainvoke_structured(
                deps.llm,
                messages,
                IntentAnalysis,
                budget=budget,
                node=NodeName.INTENT.value,
                max_regenerations=config.max_regenerations,
            )
        finally:
            usage = usage_of(budget)
        rounds = sum(1 for c in state.clarifications if c.answer is not None)
        decision = decide(reply.value, deps.calendar, config, rounds_asked=rounds)
        analysis = reply.value
        interpreted = _interpreted(state, analysis)
        update: NodeUpdate = {
            "intent": analysis,
            "interpreted_question": interpreted,
            "notices": _with_interpretation(state.notices, state.question, interpreted),
            "usage": usage,
            "regeneration_attempts": state.regeneration_attempts + reply.regenerations,
            "assumptions": decision.assumptions,
            "date_range": decision.date_range,
            "top_n": decision.top_n,
        }
        if decision.outcome is IntentOutcome.AMBIGUOUS and decision.clarification:
            update.update(
                status=S.CLARIFICATION_NEEDED,
                pending_clarification=decision.clarification,
                user_message=decision.clarification.question,
            )
        elif decision.outcome is IntentOutcome.UNCLEAR_AFTER_CLARIFICATION:
            update.update(
                status=S.FAILED,
                user_message=UNCLEAR_MESSAGE,
                error=AgentErrorInfo(
                    node=NodeName.INTENT,
                    code="UNCLEAR_AFTER_CLARIFICATION",
                    detail=f"still missing: {', '.join(decision.missing_parts)}",
                ),
            )
        else:
            update.update(status=S.UNDERSTOOD, pending_clarification=None)
        return update

    return intent_and_ambiguity
