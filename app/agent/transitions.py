"""Allowed status transitions (brief section 11) as data, plus the guard and the routes.

``check_transition`` is called for every node result: a node may keep the current status
or move along an edge in ``ALLOWED``; anything else raises ``IllegalTransition``.
``ROUTES`` says which node runs next for each (node, status) pair; it may only contain
statuses that node can produce.
"""

from collections.abc import Sequence
from itertools import pairwise

from app.core.enums import FINAL_STATUSES, NodeName, QuestionStatus
from app.core.errors import AppError

S = QuestionStatus
N = NodeName
END = "__end__"

ALLOWED: dict[QuestionStatus | None, frozenset[QuestionStatus]] = {
    None: frozenset({S.RECEIVED, S.REJECTED}),
    S.RECEIVED: frozenset({S.GUARDRAIL_CHECKED, S.BLOCKED, S.REJECTED}),
    S.GUARDRAIL_CHECKED: frozenset({S.UNDERSTOOD, S.CLARIFICATION_NEEDED}),
    S.CLARIFICATION_NEEDED: frozenset({S.UNDERSTOOD}),
    S.UNDERSTOOD: frozenset({S.SQL_GENERATED, S.BLOCKED}),
    S.SQL_GENERATED: frozenset({S.VALIDATED, S.BLOCKED}),
    S.VALIDATED: frozenset({S.EXECUTED, S.EXECUTION_FAILED}),
    S.EXECUTION_FAILED: frozenset({S.REPAIRING}),
    S.REPAIRING: frozenset({S.SQL_GENERATED}),
    S.EXECUTED: frozenset({S.ANSWERED}),
    **{final: frozenset() for final in FINAL_STATUSES},
}


class IllegalTransition(AppError):
    code = "ILLEGAL_TRANSITION"


def is_allowed(current: QuestionStatus | None, new: QuestionStatus) -> bool:
    if new == current:
        return current is not None
    if new is S.FAILED:  # any running question may fail; final states never change
        return current not in FINAL_STATUSES
    return new in ALLOWED[current]


def check_transition(
    current: QuestionStatus | None,
    new: QuestionStatus,
    node: NodeName,
    via: Sequence[QuestionStatus] = (),
) -> None:
    """Raise IllegalTransition unless ``current -> *via -> new`` follows ``ALLOWED``."""
    path: list[QuestionStatus | None] = [current, *via, new]
    for before, after in pairwise(path):
        if after is None or not is_allowed(before, after):
            raise IllegalTransition(
                f"{node}: {before.value if before else 'START'} -> "
                f"{after.value if after else 'NONE'} is not allowed"
            )


# Next node for every status a node can produce. Statuses not listed are a bug.
ROUTES: dict[NodeName, dict[QuestionStatus, str]] = {
    N.INTAKE: {S.RECEIVED: N.GUARDRAILS, S.REJECTED: N.AUDIT},
    N.GUARDRAILS: {
        S.GUARDRAIL_CHECKED: N.INTENT,
        S.BLOCKED: N.AUDIT,
        S.REJECTED: N.AUDIT,
        S.FAILED: N.AUDIT,
    },
    N.INTENT: {S.UNDERSTOOD: N.CONTEXT, S.CLARIFICATION_NEEDED: N.CLARIFICATION, S.FAILED: N.AUDIT},
    # The clarifying question is returned to the user; the run pauses after the audit.
    N.CLARIFICATION: {S.CLARIFICATION_NEEDED: N.AUDIT, S.FAILED: N.AUDIT},
    N.CONTEXT: {S.UNDERSTOOD: N.SQL_GENERATION, S.BLOCKED: N.AUDIT, S.FAILED: N.AUDIT},
    N.SQL_GENERATION: {S.SQL_GENERATED: N.VALIDATION, S.FAILED: N.AUDIT},
    N.VALIDATION: {S.VALIDATED: N.EXECUTION, S.BLOCKED: N.AUDIT, S.FAILED: N.AUDIT},
    N.EXECUTION: {S.EXECUTED: N.ANSWER, S.EXECUTION_FAILED: N.REPAIR, S.FAILED: N.AUDIT},
    N.REPAIR: {S.SQL_GENERATED: N.VALIDATION, S.FAILED: N.AUDIT},
    N.ANSWER: {S.ANSWERED: N.AUDIT, S.FAILED: N.AUDIT},
}


def next_node(node: NodeName, status: QuestionStatus | None) -> str:
    """The only routing function of the graph."""
    if node is N.AUDIT:
        return END
    routes = ROUTES[node]
    if status not in routes:
        raise IllegalTransition(f"{node}: no route for status {status}")
    return routes[status]
