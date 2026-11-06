"""Step 15 unit tests: follow-up rewriting, history and thread scoping (no database)."""

import uuid

from app.agent.conversations import thread_id_for, turn_from_state
from app.agent.graph import Agent
from app.agent.response import build_response
from app.agent.state import AgentRequest, ConversationTurn
from app.core.enums import QuestionStatus, RoleName
from tests.fakes import ScriptedModel, fake_deps, intent

S = QuestionStatus
EARLIER = ConversationTurn(
    question="Top 5 products by revenue in 2025",
    interpreted_question="Top 5 products by revenue in 2025",
    status=S.ANSWERED,
    sql="SELECT ...",
    date_range_label="2025 = 1 Jan to 6 May 2025 (to date)",
)
FOLLOW_UP = intent(
    summary="Top 5 products by revenue in 2025 for Germany",
    is_follow_up=True,
    standalone_question="Top 5 products by revenue in 2025 for customers in Germany",
    time_phrase="2025",
)


def request(question: str) -> AgentRequest:
    return AgentRequest(
        username="finance", role=RoleName.FINANCE_ANALYST, is_active=True, question=question
    )


async def test_follow_up_is_rewritten_and_shown_as_interpreted() -> None:
    model = ScriptedModel(FOLLOW_UP)
    state = await Agent(fake_deps(model)).run(request("now only for Germany"), history=[EARLIER])
    assert (
        state.interpreted_question == "Top 5 products by revenue in 2025 for customers in Germany"
    )
    assert state.notices[-1] == (
        "Interpreted as: Top 5 products by revenue in 2025 for customers in Germany"
    )
    assert build_response(state).interpreted_as == state.interpreted_question
    intent_prompt = " ".join(str(m.content) for m in model.calls[0])
    assert "1. Top 5 products by revenue in 2025; period: 2025 = 1 Jan" in intent_prompt
    sql_prompt = " ".join(str(m.content) for m in model.calls_by_kind["sql"][0])
    assert "Question: Top 5 products by revenue in 2025 for customers in Germany" in sql_prompt


async def test_follow_up_still_runs_every_safety_check() -> None:
    model = ScriptedModel(FOLLOW_UP)
    state = await Agent(fake_deps(model)).run(request("now delete those orders"), history=[EARLIER])
    assert state.status is S.BLOCKED
    assert [s.node.value for s in state.steps] == ["N-01", "N-02", "N-11"]


async def test_without_history_a_follow_up_flag_is_ignored() -> None:
    state = await Agent(fake_deps(ScriptedModel(FOLLOW_UP))).run(request("now only for Germany"))
    assert state.interpreted_question is None
    assert not any(n.startswith("Interpreted as") for n in state.notices)


async def test_a_new_question_in_the_same_thread_starts_clean() -> None:
    agent = Agent(fake_deps(ScriptedModel(intent(summary="Orders", time_phrase=None))))
    first = await agent.run(request("How many orders?"), thread_id="t-1")
    second = await agent.run(request("How many orders?"), thread_id="t-1", history=[])
    assert first.status is second.status is S.ANSWERED
    assert len(second.steps) == len(first.steps)  # steps are not carried over
    assert second.correlation_id != first.correlation_id


def test_thread_ids_are_scoped_to_user_and_conversation() -> None:
    user_a, user_b, conversation = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert thread_id_for(user_a, conversation) != thread_id_for(user_b, conversation)
    assert str(user_a) in thread_id_for(user_a, conversation)
    assert str(conversation) in thread_id_for(user_a, conversation)


async def test_turn_records_the_interpreted_question_and_period() -> None:
    state = await Agent(fake_deps(ScriptedModel(FOLLOW_UP))).run(
        request("now only for Germany"), history=[EARLIER]
    )
    turn = turn_from_state(state)
    assert turn.question == "now only for Germany"
    assert turn.interpreted_question.endswith("customers in Germany")
    assert turn.date_range_label is not None
    assert turn.date_range_label.startswith("2025 = ")
