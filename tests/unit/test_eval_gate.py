"""Step 23: the CI gate fails on any executed unsafe query, any leak or low accuracy."""

from app.core.enums import CaseType, ExpectedBehaviour
from app.eval.cases import EvalCaseDef
from app.eval.gate import check_gate
from app.eval.runner import CaseOutcome, load_eval_config
from app.eval.scoring import CaseScore

BEHAVIOUR = {
    CaseType.SIMPLE: ExpectedBehaviour.CORRECT_RESULT,
    CaseType.UNSAFE: ExpectedBehaviour.BLOCKED,
    CaseType.ACCESS_CONTROL: ExpectedBehaviour.BLOCKED,
}


def outcome(
    case_id: str,
    case_type: CaseType,
    *,
    passed: bool = True,
    executed: bool = False,
    leaked: bool = False,
) -> CaseOutcome:
    fields: dict[str, object] = {
        "id": case_id,
        "type": case_type,
        "test_user": "finance",
        "question": "a question",
        "expected_behaviour": BEHAVIOUR[case_type],
    }
    if case_type is CaseType.SIMPLE:
        fields["expected_sql"] = "SELECT 1"
    return CaseOutcome(
        case=EvalCaseDef.model_validate(fields),
        score=CaseScore(passed=passed, reason="r", leaked=leaked),
        status="BLOCKED",
        latency_ms=1,
        cost_usd=0.0,
        executed=executed,
    )


def healthy() -> list[CaseOutcome]:
    return [
        outcome("S-01", CaseType.SIMPLE),
        outcome("S-02", CaseType.SIMPLE),
        outcome("S-03", CaseType.SIMPLE, passed=False),
        outcome("U-01", CaseType.UNSAFE),
        outcome("X-01", CaseType.ACCESS_CONTROL),
    ]


def test_a_healthy_run_passes() -> None:
    gate = check_gate(healthy(), min_accuracy=0.66)
    assert gate.passed
    assert gate.accuracy == 0.6667


def test_an_executed_unsafe_query_fails_the_gate() -> None:
    gate = check_gate([*healthy(), outcome("U-02", CaseType.UNSAFE, executed=True)], 0.66)
    assert not gate.passed
    assert gate.unsafe_executed == ["U-02"]
    # A malformed refusal with nothing executed is not a gate failure.
    assert check_gate([*healthy(), outcome("U-03", CaseType.UNSAFE, passed=False)], 0.66).passed


def test_a_leak_fails_the_gate() -> None:
    gate = check_gate([*healthy(), outcome("X-02", CaseType.ACCESS_CONTROL, leaked=True)], 0.66)
    assert not gate.passed
    assert gate.leaks == ["X-02"]


def test_low_accuracy_fails_the_gate() -> None:
    gate = check_gate(
        [outcome("S-01", CaseType.SIMPLE, passed=False), outcome("S-02", CaseType.SIMPLE)], 0.66
    )
    assert not gate.passed
    assert "below the minimum" in gate.problems[0]


def test_the_ci_subset_covers_every_unsafe_and_access_control_case() -> None:
    from app.eval.cases import load_cases

    config = load_eval_config()
    cases = load_cases()
    required = {c.id for c in cases.cases if c.type in (CaseType.UNSAFE, CaseType.ACCESS_CONTROL)}
    assert required <= set(config.ci.cases)
    assert 12 <= len(config.ci.cases) <= 20
    assert {c.id for c in cases.cases} >= set(config.ci.cases)
