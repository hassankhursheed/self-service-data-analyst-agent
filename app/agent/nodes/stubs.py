"""Stub nodes N-10 and N-11. Each returns a fixed result until its own step replaces it.

They exist so the graph, routing and transitions can be tested end to end now. Neither
calls the LLM or the database.
"""

from app.agent.nodes.base import NodeUpdate, agent_node
from app.agent.state import AgentState, Answer
from app.core.enums import NodeName, QuestionStatus

S = QuestionStatus


@agent_node(NodeName.ANSWER)
async def answer_and_visualization(state: AgentState) -> NodeUpdate:
    return {
        "status": S.ANSWERED,
        "answer": Answer(text="(stub answer)"),
        "user_message": "(stub answer)",
    }


@agent_node(NodeName.AUDIT)
async def audit_and_metrics(state: AgentState) -> NodeUpdate:
    return {"finished": True}
