"""Stub nodes N-05 to N-11. Each returns a fixed result until its own step replaces it.

They exist so the graph, routing and transitions can be tested end to end now. None of
them calls the LLM or the database.
"""

from app.agent.nodes.base import NodeUpdate, agent_node
from app.agent.state import AgentState, Answer, GeneratedSQL
from app.core.enums import NodeName, QuestionStatus
from app.db.analytics import QueryResult

S = QuestionStatus


@agent_node(NodeName.CONTEXT)
async def context_retrieval(state: AgentState) -> NodeUpdate:
    return {"status": S.UNDERSTOOD}


@agent_node(NodeName.SQL_GENERATION)
async def sql_generation(state: AgentState) -> NodeUpdate:
    return {"status": S.SQL_GENERATED, "generated": GeneratedSQL(sql="SELECT 1 AS stub")}


@agent_node(NodeName.VALIDATION)
async def sql_validation(state: AgentState) -> NodeUpdate:
    return {"status": S.VALIDATED}


@agent_node(NodeName.EXECUTION)
async def execution(state: AgentState) -> NodeUpdate:
    result = QueryResult(columns=["stub"], rows=[(1,)], row_count=1, truncated=False)
    return {"status": S.EXECUTED, "execution": result}


@agent_node(NodeName.REPAIR)
async def repair(state: AgentState) -> NodeUpdate:
    return {
        "status": S.SQL_GENERATED,
        "via": [S.REPAIRING],
        "repair_attempts": state.repair_attempts + 1,
        "generated": GeneratedSQL(sql="SELECT 1 AS stub"),
    }


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
