"""Stub node N-11. It returns a fixed result until Step 16 adds the audit trail."""

from app.agent.nodes.base import NodeUpdate, agent_node
from app.agent.state import AgentState
from app.core.enums import NodeName


@agent_node(NodeName.AUDIT)
async def audit_and_metrics(state: AgentState) -> NodeUpdate:
    return {"finished": True}
