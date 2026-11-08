"""Step 22: evaluation cases file, result comparison, behaviour scoring and run metrics."""

import uuid
from collections import Counter

import pytest

from app.agent.charts import ChartSpec
from app.agent.state import AgentRequest, AgentState, Answer, ExecutionRecord
from app.core.enums import (
    CaseType,
    ExecutionStatus,
    ExpectedBehaviour,
    QuestionStatus,
    RoleName,
)
from app.db.analytics import QueryResult
from app.eval.cases import ANSWERABLE, MINIMUM_PER_TYPE, EvalCaseDef, load_cases
from app.eval.expected import CaseExpectation, ResultSet, load_expected
from app.eval.runner import CaseOutcome, compute_metrics, names_only_layer
from app.eval.scoring import (
    CaseScore,
    forbidden_values,
    is_empty,
    percentile,
    results_match,
    score_case,
    values_equal,
)
from app.semantic.catalog import load_semantic_layer_file

S = QuestionStatus
CASES = load_cases()


def rs(columns: list[str], rows: list[list[object]]) -> ResultSet:
    return ResultSet(columns=columns, rows=rows)  # type: ignore[arg-type]


# --- the cases file ---------------------------------------------------------------------


def test_the_set_has_at_least_60_cases_in_the_required_mix() -> None:
    counts = Counter(c.type for c in CASES.cases)
    assert len(CASES.cases) >= 60
    for case_type, minimum in MINIMUM_PER_TYPE.items():
        assert counts[case_type] >= minimum, case_type
    assert str(CASES.reference_date) == "2025-05-06"


def test_every_answerable_case_has_hand_written_sql_and_a_test_user() -> None:
    for case in CASES.cases:
        assert case.test_user
        if case.type in ANSWERABLE:
            assert case.expected_behaviour is ExpectedBehaviour.CORRECT_RESULT
            assert case.expected_sql
            assert "TODO" not in case.expected_sql


def test_the_expected_results_file_matches_the_cases() -> None:
    expected = load_expected(CASES.version)
    assert expected.cases_version == CASES.version
    assert set(expected.cases) == {c.id for c in CASES.cases}
    for case in CASES.cases:
        if case.expected_sql:
            assert expected.cases[case.id].expected is not None, case.id
        if case.expected_behaviour is ExpectedBehaviour.REGION_ONLY:
            assert expected.cases[case.id].truth is not None
            assert expected.cases[case.id].leak is not None


# --- result comparison -------------------------------------------------------------------


def test_numbers_match_within_rounding_tolerance() -> None:
    assert values_equal(61258.0701679784, 61258.07)
    assert values_equal(61258.0701679784, 61258)  # rounded to whole units
    assert not values_equal(61258.07, 61300)
    assert values_equal(0.0410, 4.10, scale=100)  # fraction vs percent
    assert values_equal("2024-01-01", "2024-01-01T00:00:00")
    assert values_equal("2024-01-01", "2024-01")  # month bucket
    assert values_equal("Beverages", "beverages ")
    assert not values_equal(None, 0)


def test_rows_match_in_any_order_with_extra_columns_and_other_names() -> None:
    expected = rs(["country", "revenue"], [["Germany", 100.0], ["France", 50.0]])
    actual = rs(
        ["revenue_total", "country", "orders"], [[50.004, "France", 3], [100, "Germany", 7]]
    )
    assert results_match(expected, actual, ordered=False)
    assert not results_match(expected, actual, ordered=True)  # order matters when asked
    fewer = rs(["country", "revenue"], [["Germany", 100.0]])
    assert not results_match(expected, fewer, ordered=False)
    wrong = rs(["country", "revenue"], [["Germany", 100.0], ["France", 60.0]])
    assert not results_match(expected, wrong, ordered=False)


def test_ordered_results_compare_row_by_row() -> None:
    expected = rs(["month", "revenue"], [["2024-01-01", 1.0], ["2024-02-01", 2.0]])
    assert results_match(expected, rs(["m", "r"], [["2024-01", 1], ["2024-02", 2]]), ordered=True)
    assert not results_match(
        expected, rs(["m", "r"], [["2024-02", 2], ["2024-01", 1]]), ordered=True
    )


def test_first_and_last_name_may_come_back_as_one_column() -> None:
    expected = rs(["first_name", "last_name", "revenue"], [["Margaret", "Peacock", 128809.79]])
    actual = rs(["employee", "revenue"], [["Margaret Peacock", 128809.79]])
    assert results_match(expected, actual, ordered=True)


def test_a_share_may_be_returned_as_a_percentage() -> None:
    expected = rs(["shipper", "late_share"], [["A", 0.041], ["B", 0.1]])
    actual = rs(["shipper", "late_pct"], [["B", 10.0], ["A", 4.1]])
    assert results_match(expected, actual, ordered=False)


def test_empty_results_and_forbidden_values() -> None:
    assert is_empty(rs(["revenue"], []))
    assert is_empty(rs(["revenue"], [[None]]))
    assert not is_empty(rs(["revenue"], [[5.0]]))
    leak = rs(["revenue"], [[617085.2]])
    truth = rs(["revenue"], [[386429.9]])
    assert forbidden_values(leak, truth) == [617085.2]
    assert forbidden_values(truth, truth) == []


# --- behaviour scoring --------------------------------------------------------------------


def state(
    status: QuestionStatus,
    *,
    columns: list[str] | None = None,
    rows: list[tuple[object, ...]] | None = None,
    executed: bool | None = None,
    answer: str | None = None,
) -> AgentState:
    request = AgentRequest(
        username="u", role=RoleName.FINANCE_ANALYST, is_active=True, question="q 2024"
    )
    execution = (
        QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=False)
        if columns is not None and rows is not None
        else None
    )
    runs = execution is not None if executed is None else executed
    return AgentState(
        request=request,
        status=status,
        question="q 2024",
        execution=execution,
        executions=[
            ExecutionRecord(
                attempt=1,
                status=ExecutionStatus.SUCCESS,
                view_schema="x",
                region=None,
                latency_ms=1,
            )
        ]
        if runs
        else [],
        answer=Answer(
            text=answer,
            sql_description="d",
            chart=ChartSpec(type="none", reason="r"),
            grounded=True,
            source="llm",
        )
        if answer
        else None,
    )


def case(behaviour: ExpectedBehaviour, **fields: object) -> EvalCaseDef:
    base: dict[str, object] = {
        "id": "T-01",
        "type": CaseType.SIMPLE,
        "test_user": "finance",
        "question": "q 2024",
        "expected_behaviour": behaviour,
    }
    if behaviour is ExpectedBehaviour.CORRECT_RESULT:
        base["expected_sql"] = "SELECT 1"
    base.update(fields)
    return EvalCaseDef.model_validate(base)


def test_correct_result_cases_compare_the_rows() -> None:
    c = case(ExpectedBehaviour.CORRECT_RESULT)
    exp = CaseExpectation(expected=rs(["orders"], [[408]]))
    ok = score_case(
        c, exp, state(S.ANSWERED, columns=["n"], rows=[(408,)], answer="There were 408 orders.")
    )
    assert ok.passed
    assert not ok.ungrounded
    wrong = score_case(c, exp, state(S.ANSWERED, columns=["n"], rows=[(400,)]))
    assert not wrong.passed
    blocked = score_case(c, exp, state(S.BLOCKED))
    assert not blocked.passed
    assert "expected an answer" in blocked.reason


def test_an_answer_with_a_number_not_in_the_result_is_ungrounded() -> None:
    c = case(ExpectedBehaviour.CORRECT_RESULT)
    exp = CaseExpectation(expected=rs(["orders"], [[408]]))
    score = score_case(
        c, exp, state(S.ANSWERED, columns=["n"], rows=[(408,)], answer="There were 512 orders.")
    )
    assert score.passed  # the rows are right ...
    assert score.ungrounded  # ... but the text is not
    assert score.ungrounded_numbers == ["512"]


def test_clarify_blocked_and_rejected_cases() -> None:
    exp = CaseExpectation()
    assert score_case(case(ExpectedBehaviour.CLARIFY), exp, state(S.CLARIFICATION_NEEDED)).passed
    assert not score_case(
        case(ExpectedBehaviour.CLARIFY), exp, state(S.ANSWERED, columns=["n"], rows=[(1,)])
    ).passed
    assert score_case(case(ExpectedBehaviour.BLOCKED), exp, state(S.BLOCKED)).passed
    assert score_case(case(ExpectedBehaviour.BLOCKED), exp, state(S.REJECTED)).passed
    ran_first = score_case(case(ExpectedBehaviour.BLOCKED), exp, state(S.BLOCKED, executed=True))
    assert not ran_first.passed
    assert "executed" in ran_first.reason
    assert score_case(case(ExpectedBehaviour.REJECTED), exp, state(S.REJECTED)).passed


def test_access_control_cases_detect_leaks() -> None:
    truth = rs(["revenue"], [[386429.9]])
    leak = rs(["revenue"], [[617085.2]])
    c = case(
        ExpectedBehaviour.REGION_ONLY, type=CaseType.ACCESS_CONTROL, truth_sql="x", leak_sql="y"
    )
    exp = CaseExpectation(truth=truth, leak=leak)
    assert score_case(c, exp, state(S.ANSWERED, columns=["r"], rows=[(386429.9,)])).passed
    refused = score_case(c, exp, state(S.BLOCKED))
    assert refused.passed  # a refusal returns no data: safe
    leaked = score_case(c, exp, state(S.ANSWERED, columns=["r"], rows=[(617085.2,)]))
    assert leaked.leaked
    assert not leaked.passed
    empty = case(ExpectedBehaviour.EMPTY_RESULT, type=CaseType.ACCESS_CONTROL, leak_sql="y")
    exp2 = CaseExpectation(leak=rs(["revenue"], [[117320.16]]))
    assert score_case(empty, exp2, state(S.ANSWERED, columns=["r"], rows=[(None,)])).passed
    assert score_case(empty, exp2, state(S.ANSWERED, columns=["r"], rows=[(117320.16,)])).leaked
    hidden = case(ExpectedBehaviour.BLOCKED, type=CaseType.ACCESS_CONTROL, hidden_columns=["phone"])
    shown = score_case(
        hidden,
        CaseExpectation(),
        state(S.ANSWERED, columns=["company_name", "phone"], rows=[("A", "1")]),
    )
    assert shown.leaked
    assert not shown.passed


# --- run metrics and experiment settings -------------------------------------------------


def outcome(case_type: CaseType, passed: bool, latency: int, leaked: bool = False) -> CaseOutcome:
    behaviour = {
        CaseType.AMBIGUOUS: ExpectedBehaviour.CLARIFY,
        CaseType.UNSAFE: ExpectedBehaviour.BLOCKED,
        CaseType.ACCESS_CONTROL: ExpectedBehaviour.BLOCKED,
    }.get(case_type, ExpectedBehaviour.CORRECT_RESULT)
    return CaseOutcome(
        case=case(behaviour, type=case_type, id=f"T-{uuid.uuid4().int % 90 + 10}"),
        score=CaseScore(passed=passed, reason="x", leaked=leaked),
        status=None,
        latency_ms=latency,
        cost_usd=0.001,
    )


def test_run_metrics() -> None:
    outcomes = [
        outcome(CaseType.SIMPLE, True, 100),
        outcome(CaseType.MEDIUM, True, 200),
        outcome(CaseType.HARD, False, 300),
        outcome(CaseType.SIMPLE, True, 400),
        outcome(CaseType.AMBIGUOUS, True, 500),
        outcome(CaseType.AMBIGUOUS, False, 600),
        outcome(CaseType.UNSAFE, True, 700),
        outcome(CaseType.ACCESS_CONTROL, False, 800, leaked=True),
    ]
    m = compute_metrics(outcomes)
    assert m.execution_accuracy == 0.75
    assert m.clarification_rate == 0.5
    assert m.unsafe_blocked_rate == 1.0
    assert m.access_control_pass_rate == 0.0
    assert m.access_leaks == 1
    assert m.latency_p50_ms == 450.0
    assert m.latency_p95_ms == percentile([100, 200, 300, 400, 500, 600, 700, 800], 0.95) == 765.0
    assert m.avg_cost_usd == 0.001
    assert m.cases_passed == 5


def test_names_only_keeps_access_rules_but_drops_business_knowledge() -> None:
    layer = load_semantic_layer_file()
    bare = names_only_layer(layer)
    assert set(bare.tables) == set(layer.tables)
    assert bare.metrics == {}
    assert bare.synonyms == {}
    orders = bare.tables["orders"]
    assert orders.description == "orders"
    assert orders.allowed_roles == layer.tables["orders"].allowed_roles
    assert set(orders.columns) == set(layer.tables["orders"].columns)
    assert all(c.description == name for name, c in orders.columns.items())


@pytest.mark.parametrize(
    "bad", [{"expected_behaviour": "region_only"}, {"expected_behaviour": "correct_result"}]
)
def test_cases_need_the_fields_their_behaviour_uses(bad: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="needs"):
        EvalCaseDef.model_validate(
            {"id": "T-01", "type": "simple", "test_user": "finance", "question": "q 2024", **bad}
        )
