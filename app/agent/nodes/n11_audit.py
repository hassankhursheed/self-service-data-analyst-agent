"""N-11 Audit and Metrics: write the audit trail. A failed write never breaks the answer."""

import datetime as dt
import logging

from app.agent.deps import AgentDeps
from app.agent.nodes.base import NodeFn, NodeUpdate, agent_node
from app.agent.state import AgentState
from app.core.enums import NodeName

logger = logging.getLogger(__name__)


def make_audit_node(deps: AgentDeps) -> NodeFn:
    @agent_node(NodeName.AUDIT)
    async def audit_and_metrics(state: AgentState) -> NodeUpdate:
        started = dt.datetime.now(dt.UTC)
        try:
            await deps.audit.record(state, audit_started=started)
        except Exception:
            # The user still gets their answer; the failure is logged for operators.
            logger.exception("audit write failed for correlation_id=%s", state.correlation_id)
            return {"finished": True, "audit_ok": False}
        return {"finished": True, "audit_ok": True}

    return audit_and_metrics
