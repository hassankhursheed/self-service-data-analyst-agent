"""N-03 Intent and Ambiguity: LLM analysis (structured output) plus a fixed decision rule."""

from app.agent.deps import AgentDeps, usage_of
from app.agent.intent import IntentAnalysis, IntentOutcome, decide
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.state import AgentErrorInfo, AgentState
from app.core.enums import NodeName, QuestionStatus, RoleName
from app.core.errors import AppError
from app.core.llm import ainvoke_structured
from app.core.prompts import load_prompt

S = QuestionStatus
UNCLEAR_MESSAGE = (
    "I still couldn't tell exactly what you need. Please ask again and include the measure "
    "(for example revenue or number of orders) and the period."
)


def _metrics_text(deps: AgentDeps, role: RoleName) -> str:
    lines = [
        f"- {name}: {m.description}" + (f" (also: {', '.join(m.synonyms)})" if m.synonyms else "")
        for name, m in deps.semantic.metrics.items()
        if role in m.allowed_roles
    ]
    return "\n".join(lines) or "- (none)"


def _tables_text(deps: AgentDeps, role: RoleName) -> str:
    return ", ".join(t for t, d in deps.semantic.tables.items() if role in d.allowed_roles)


def _clarifications_text(state: AgentState) -> str:
    answered = [c for c in state.clarifications if c.answer is not None]
    if not answered:
        return "none"
    return " | ".join(f"Asked: {c.question} Answer: {c.answer}" for c in answered)


def make_intent_node(deps: AgentDeps) -> NodeFn:
    @agent_node(NodeName.INTENT)
    async def intent_and_ambiguity(state: AgentState) -> NodeUpdate:
        if state.user is None:
            raise AppError("intent reached without a user context")
        prompt = load_prompt("intent", deps.llm_config.prompts["intent"])
        messages = [
            *deps.system_messages(),
            *prompt.to_chat_prompt().format_messages(
                business_today=deps.calendar.reference_date.isoformat(),
                metrics=_metrics_text(deps, state.user.role),
                tables=_tables_text(deps, state.user.role),
                question=state.question,
                clarifications=_clarifications_text(state),
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
        update: NodeUpdate = {
            "intent": reply.value,
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
