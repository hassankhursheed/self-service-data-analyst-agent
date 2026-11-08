"""Step 12: intent, ambiguity and clarification (LLM mocked)."""

import datetime as dt

import pytest

from app.agent.config import load_agent_config
from app.agent.graph import Agent
from app.agent.intent import IntentAnalysis, IntentOutcome, decide, template_clarification
from app.agent.state import AgentRequest, StepRecord
from app.core.enums import NodeName, QuestionStatus, RoleName
from app.core.errors import AppError
from app.semantic.calendar import load_calendar
from tests.fakes import ScriptedModel, fake_deps, intent

S = QuestionStatus
CAL = load_calendar()
CFG = load_agent_config().intent

TOP_CUSTOMERS = intent(
    summary="Top customers",
    metric=None,
    metric_options=["revenue", "number_of_orders"],
    time_phrase=None,
    grouping="customer",
    missing=[
        {"part": "metric", "reason": "top could mean revenue or number of orders"},
        {"part": "time_range", "reason": "no period given"},
    ],
    clarifying_question="Top customers by revenue or by number of orders, and for which year?",
    options=["By revenue, 2024", "By number of orders, 2024", "By revenue, this year"],
)
REVENUE_LAST_QUARTER = intent(summary="Revenue last quarter", time_phrase="last quarter")


def request(question: str, role: RoleName = RoleName.FINANCE_ANALYST) -> AgentRequest:
    return AgentRequest(username="finance", role=role, is_active=True, question=question)


def nodes(steps: list[StepRecord]) -> list[str]:
    return [s.node.value for s in steps]


# --- decision rules (pure) -------------------------------------------------------------------


def test_clear_question_with_resolved_period() -> None:
    decision = decide(IntentAnalysis.model_validate(REVENUE_LAST_QUARTER), CAL, CFG)
    assert decision.outcome is IntentOutcome.CLEAR
    assert decision.date_range is not None
    assert decision.date_range.label == "Last quarter = 1 Jan to 31 Mar 2025"


def test_missing_metric_asks() -> None:
    decision = decide(IntentAnalysis.model_validate(TOP_CUSTOMERS), CAL, CFG)
    assert decision.outcome is IntentOutcome.AMBIGUOUS
    assert decision.missing_parts == ["metric", "time_range"]
    assert decision.clarification is not None
    assert 2 <= len(decision.clarification.options) <= 4


def test_only_missing_time_becomes_a_stated_assumption() -> None:
    analysis = IntentAnalysis.model_validate(
        intent(time_phrase=None, missing=[{"part": "time_range", "reason": "no period"}])
    )
    decision = decide(analysis, CAL, CFG)
    assert decision.outcome is IntentOutcome.ASSUMED
    assert decision.date_range is not None
    assert decision.date_range.from_date == dt.date(2025, 1, 1)
    assert decision.assumptions == [
        "No time period given: assumed This year = 1 Jan to 6 May 2025."
    ]


def test_missing_top_n_uses_the_default() -> None:
    analysis = IntentAnalysis.model_validate(
        intent(grouping="product", missing=[{"part": "top_n", "reason": "how many?"}])
    )
    decision = decide(analysis, CAL, CFG)
    assert decision.top_n == CFG.default_top_n
    assert any("top 10" in a for a in decision.assumptions)


def test_unresolvable_time_phrase_counts_as_missing() -> None:
    analysis = IntentAnalysis.model_validate(
        intent(time_phrase="since forever", metric=None, missing=[{"part": "metric"}])
    )
    decision = decide(analysis, CAL, CFG)
    assert decision.outcome is IntentOutcome.AMBIGUOUS
    assert "time_range" in decision.missing_parts


def test_named_month_without_year_records_the_calendar_assumption() -> None:
    decision = decide(IntentAnalysis.model_validate(intent(time_phrase="March")), CAL, CFG)
    assert decision.outcome is IntentOutcome.ASSUMED
    assert decision.assumptions == ["No year given: used the most recent March."]


def test_rounds_are_limited() -> None:
    analysis = IntentAnalysis.model_validate(TOP_CUSTOMERS)
    decision = decide(analysis, CAL, CFG, rounds_asked=CFG.max_clarification_rounds)
    assert decision.outcome is IntentOutcome.UNCLEAR_AFTER_CLARIFICATION


def test_template_question_when_the_model_gives_none() -> None:
    draft = template_clarification(["metric", "time_range"], [], CFG)
    assert (
        draft.question
        == "Do you mean by revenue or by number of orders, and for which year or period?"
    )
    assert 2 <= len(draft.options) <= 4


def test_model_question_without_enough_options_falls_back_to_the_template() -> None:
    analysis = IntentAnalysis.model_validate({**TOP_CUSTOMERS, "options": ["only one"]})
    decision = decide(analysis, CAL, CFG)
    assert decision.clarification is not None
    assert decision.clarification.question.startswith("Do you mean by revenue")


# --- graph: N-03 and N-04 ---------------------------------------------------------------------


async def test_top_customers_asks_by_revenue_or_orders_and_which_year() -> None:
    agent = Agent(fake_deps(ScriptedModel(TOP_CUSTOMERS)))
    state = await agent.run(request("Top customers"))
    assert state.status is S.CLARIFICATION_NEEDED
    assert state.awaiting_reply is True
    assert state.pending_clarification is not None
    question = state.pending_clarification.question
    assert "revenue" in question
    assert "number of orders" in question
    assert "year" in question
    assert 2 <= len(state.pending_clarification.options) <= 4
    assert state.user_message == question
    assert nodes(state.steps) == ["N-01", "N-02", "N-03"]  # paused inside N-04


async def test_revenue_last_quarter_continues_with_the_resolved_range() -> None:
    agent = Agent(fake_deps(ScriptedModel(REVENUE_LAST_QUARTER)))
    state = await agent.run(request("Revenue last quarter"))
    assert state.status is S.ANSWERED
    assert state.awaiting_reply is False
    assert state.clarifications == []
    assert state.date_range is not None
    assert state.date_range.label == "Last quarter = 1 Jan to 31 Mar 2025"


async def test_resumed_clarification_reaches_understood_with_the_chosen_option() -> None:
    after_reply = intent(
        summary="Top customers by revenue in 2024", grouping="customer", time_phrase="2024"
    )
    model = ScriptedModel(TOP_CUSTOMERS, after_reply)
    agent = Agent(fake_deps(model))
    paused = await agent.run(request("Top customers"))
    assert paused.thread_id is not None
    state = await agent.resume(paused.thread_id, "By revenue, 2024")

    assert state.status is S.ANSWERED
    assert [c.answer for c in state.clarifications] == ["By revenue, 2024"]
    record = state.clarifications[0]
    assert record.round == 1
    assert record.missing_parts == ["metric", "time_range"]
    assert record.answered_at is not None
    assert nodes(state.steps)[:6] == ["N-01", "N-02", "N-03", "N-04", "N-03", "N-05"]
    transitions = [(s.node.value, s.to_status) for s in state.steps]
    assert ("N-03", S.UNDERSTOOD) in transitions
    assert state.date_range is not None
    assert state.date_range.label == "2024 = 1 Jan to 31 Dec 2024"
    # The second analysis saw the user's answer.
    assert "By revenue, 2024" in str(model.calls[-1][-1].content)


async def test_still_unclear_reply_asks_a_second_round_then_fails() -> None:
    agent = Agent(fake_deps(ScriptedModel(TOP_CUSTOMERS)))
    first = await agent.run(request("Top customers"))
    assert first.thread_id is not None
    second = await agent.resume(first.thread_id, "whatever")
    assert second.status is S.CLARIFICATION_NEEDED
    assert second.awaiting_reply is True
    final = await agent.resume(first.thread_id, "not sure")
    assert final.status is S.FAILED
    assert final.error is not None
    assert final.error.code == "UNCLEAR_AFTER_CLARIFICATION"
    assert len(final.clarifications) == CFG.max_clarification_rounds
    assert final.user_message is not None
    assert "measure" in final.user_message


async def test_resume_without_a_pending_question_is_refused() -> None:
    agent = Agent(fake_deps(ScriptedModel(REVENUE_LAST_QUARTER)))
    state = await agent.run(request("Revenue last quarter"))
    assert state.thread_id is not None
    with pytest.raises(AppError, match="not waiting"):
        await agent.resume(state.thread_id, "By revenue")


# --- malformed output ------------------------------------------------------------------------


async def test_malformed_output_is_regenerated_once() -> None:
    model = ScriptedModel("Sure! The answer is revenue.", REVENUE_LAST_QUARTER)
    agent = Agent(fake_deps(model))
    state = await agent.run(request("Revenue last quarter"))
    assert state.status is S.ANSWERED
    assert len(model.calls) == 2
    assert state.regeneration_attempts == 1
    assert "not valid" in str(model.calls[1][-1].content)


async def test_malformed_output_twice_fails_safely() -> None:
    model = ScriptedModel('{"summary": 3, "unexpected": true}', "not json at all")
    agent = Agent(fake_deps(model))
    state = await agent.run(request("Revenue last quarter"))
    assert state.status is S.FAILED
    assert state.error is not None
    assert state.error.code == "MALFORMED_OUTPUT"
    assert state.error.node is NodeName.INTENT
    assert len(model.calls) == 2  # one regeneration, never more
    assert state.user_message is not None
    assert "rephras" in state.user_message
    assert [s.node.value for s in state.steps][-1] == "N-11"


async def test_llm_usage_is_recorded_in_the_state() -> None:
    agent = Agent(fake_deps(ScriptedModel(REVENUE_LAST_QUARTER)))
    state = await agent.run(request("Revenue last quarter"))
    # Intent, SQL generation and answer calls, 50 in / 20 out each, added up.
    assert state.usage.input_tokens == 150
    assert state.usage.output_tokens == 60
    assert state.usage.cost_usd > 0


async def test_intent_prompt_only_offers_metrics_the_role_may_use() -> None:
    model = ScriptedModel(REVENUE_LAST_QUARTER)
    agent = Agent(fake_deps(model))
    await agent.run(request("How many units did we ship?", role=RoleName.OPERATIONS_MANAGER))
    prompt_text = " ".join(str(m.content) for m in model.calls[0])
    assert "units_sold" in prompt_text
    assert "- revenue:" not in prompt_text
    assert "Business today is 2025-05-06" in prompt_text


def test_null_lists_from_the_model_mean_empty_lists() -> None:
    """Found by the evaluation: Ministral writes null instead of [] for empty lists."""
    from app.agent.intent import IntentAnalysis
    from app.agent.sql_output import GeneratedSQL

    parsed = IntentAnalysis.model_validate(
        {
            "summary": "Orders in 2024",
            "metric": "number_of_orders",
            "metric_options": None,
            "entities": None,
            "missing": None,
            "assumptions": None,
            "options": None,
        }
    )
    assert (parsed.metric_options, parsed.entities, parsed.missing, parsed.options) == (
        [],
        [],
        [],
        [],
    )
    sql = GeneratedSQL.model_validate(
        {
            "sql": "SELECT 1",
            "tables_used": ["orders"],
            "metrics_used": None,
            "assumptions": None,
            "confidence": "high",
        }
    )
    assert (sql.metrics_used, sql.assumptions) == ([], [])
    with pytest.raises(ValueError, match="tables_used"):
        GeneratedSQL.model_validate({"sql": "SELECT 1", "tables_used": None, "confidence": "high"})


def test_the_intent_prompt_says_whose_data_it_is() -> None:
    from app.agent.nodes.n03_intent import user_scope
    from app.core.enums import RegionCode

    sales = user_scope(RoleName.SALES_MANAGER, RegionCode.EUROPE)
    assert "EUROPE" in sales
    assert "my region" in sales
    assert "all regions" in user_scope(RoleName.FINANCE_ANALYST, None)
