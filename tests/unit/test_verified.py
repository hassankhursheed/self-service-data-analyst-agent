"""Step 20: verified query library: seed file, similarity search and use in N-05 / N-06."""

import dataclasses
import uuid

import pytest

from app.agent.config import load_agent_config
from app.agent.graph import Agent
from app.agent.state import AgentRequest
from app.core.enums import QuestionStatus, RoleName
from app.safety.sql_validator import validate
from app.semantic.catalog import load_semantic_layer_file
from app.semantic.verified import (
    VerifiedConfig,
    VerifiedExample,
    examples_text,
    find_verified_examples,
    lineage_for,
    load_seed_file,
    similarity,
)
from app.services.verified_library import LibraryInputError, SqlInvalid, check_sql_for_roles
from tests.fakes import ScriptedModel, fake_deps, intent, sql_reply

LAYER = load_semantic_layer_file()
SEED = load_seed_file()
CONFIG = VerifiedConfig(enabled=True, max_examples=3, min_score=0.4)
S = QuestionStatus


def library() -> list[VerifiedExample]:
    """The seeded examples as the database would return them."""
    out = []
    for ex in SEED.examples:
        tables = sorted({t for r in ex.allowed_roles for t in validate(ex.sql, r, LAYER).tables})
        out.append(
            VerifiedExample(
                id=uuid.uuid5(lineage_for(ex.key), "v1"),
                lineage_id=lineage_for(ex.key),
                version=1,
                question=ex.question,
                sql=ex.sql,
                description=ex.description,
                tables=tables,
                metrics=ex.metrics,
                allowed_roles=ex.allowed_roles,
            )
        )
    return out


def by_key(key: str) -> VerifiedExample:
    target = lineage_for(key)
    return next(ex for ex in library() if ex.lineage_id == target)


# --- the seed file -----------------------------------------------------------------------


def test_the_library_seeds_at_least_15_unique_examples() -> None:
    keys = [ex.key for ex in SEED.examples]
    assert len(keys) >= 15
    assert len(set(keys)) == len(keys)
    assert len({ex.question.lower() for ex in SEED.examples}) == len(keys)


@pytest.mark.parametrize("example", SEED.examples, ids=lambda ex: ex.key)
def test_every_seeded_example_passes_the_validator_for_each_allowed_role(example: object) -> None:
    from app.semantic.verified import SeedExample

    assert isinstance(example, SeedExample)
    for role in example.allowed_roles:
        assert role is not RoleName.ADMIN
        result = validate(example.sql, role, LAYER)
        assert result.allowed, (role, result.reason_code, result.detail)
    for metric in example.metrics:
        allowed = set(LAYER.metrics[metric].allowed_roles)
        assert set(example.allowed_roles) <= allowed, (metric, example.allowed_roles)


def test_the_library_has_examples_limited_to_one_role() -> None:
    finance_only = [ex for ex in SEED.examples if ex.allowed_roles == [RoleName.FINANCE_ANALYST]]
    assert finance_only, "expected at least one finance-only example"


# --- similarity search -------------------------------------------------------------------


def test_a_similar_question_finds_its_verified_example_first() -> None:
    found = find_verified_examples(
        "What was the total revenue in the last quarter?",
        RoleName.FINANCE_ANALYST,
        library(),
        LAYER,
        CONFIG,
    )
    assert found
    assert found[0].lineage_id == lineage_for("revenue-last-quarter")
    assert len(found) <= CONFIG.max_examples
    assert (
        similarity("What was the total revenue in the last quarter?", found[0]) >= CONFIG.min_score
    )


def test_an_unrelated_question_gets_no_examples() -> None:
    assert (
        find_verified_examples("Hello there", RoleName.FINANCE_ANALYST, library(), LAYER, CONFIG)
        == []
    )


def test_a_disabled_example_is_never_retrieved() -> None:
    examples = [
        ex.model_copy(update={"is_active": False})
        if ex.lineage_id == lineage_for("revenue-last-quarter")
        else ex
        for ex in library()
    ]
    found = find_verified_examples(
        "What was our total revenue last quarter?",
        RoleName.FINANCE_ANALYST,
        examples,
        LAYER,
        CONFIG,
    )
    assert all(ex.lineage_id != lineage_for("revenue-last-quarter") for ex in found)


def test_a_sales_role_never_receives_a_finance_only_example() -> None:
    question = by_key("freight-share-of-revenue").question
    finance = find_verified_examples(question, RoleName.FINANCE_ANALYST, library(), LAYER, CONFIG)
    assert finance[0].lineage_id == lineage_for("freight-share-of-revenue")
    for role in (RoleName.SALES_MANAGER, RoleName.OPERATIONS_MANAGER):
        found = find_verified_examples(question, role, library(), LAYER, CONFIG)
        assert all(role in ex.allowed_roles for ex in found)
        assert all(ex.lineage_id != lineage_for("freight-share-of-revenue") for ex in found)


def test_an_example_that_fails_validation_for_the_role_is_dropped() -> None:
    bad = by_key("revenue-last-quarter").model_copy(
        update={
            "id": uuid.uuid4(),
            "sql": "DELETE FROM orders",
            "question": "total revenue last quarter",
        }
    )
    found = find_verified_examples(
        "total revenue last quarter", RoleName.FINANCE_ANALYST, [bad], LAYER, CONFIG
    )
    assert found == []


def test_examples_are_off_when_the_config_says_so() -> None:
    off = CONFIG.model_copy(update={"enabled": False})
    assert (
        find_verified_examples(
            "revenue last quarter", RoleName.FINANCE_ANALYST, library(), LAYER, off
        )
        == []
    )


def test_the_agent_config_has_the_verified_examples_section() -> None:
    config = load_agent_config().verified_examples
    assert config.enabled
    assert 1 <= config.max_examples <= 10


def test_the_few_shot_text_shows_question_description_and_sql() -> None:
    text = examples_text([by_key("revenue-last-quarter")])
    assert "What was our total revenue last quarter?" in text
    assert "SELECT SUM(od.unit_price" in text
    assert examples_text([]) == "none"


# --- saving rules (admin side) -----------------------------------------------------------


def test_saved_sql_must_pass_the_validator_for_every_allowed_role() -> None:
    sql = by_key("revenue-last-quarter").sql
    assert set(check_sql_for_roles(sql, [RoleName.FINANCE_ANALYST], ["revenue"], LAYER)) == {
        "orders",
        "order_details",
    }
    with pytest.raises(SqlInvalid):
        check_sql_for_roles("DROP TABLE orders", [RoleName.FINANCE_ANALYST], [], LAYER)
    with pytest.raises(LibraryInputError):  # revenue is not an operations metric
        check_sql_for_roles(sql, [RoleName.OPERATIONS_MANAGER], ["revenue"], LAYER)
    with pytest.raises(LibraryInputError):
        check_sql_for_roles(sql, [RoleName.ADMIN], [], LAYER)
    with pytest.raises(LibraryInputError):
        check_sql_for_roles(sql, [], [], LAYER)


# --- in the graph ------------------------------------------------------------------------

REVENUE_Q1 = intent(
    summary="Total revenue last quarter", metric="revenue", time_phrase="last quarter"
)
Q1_SQL = by_key("revenue-last-quarter").sql


def request(question: str, role: RoleName = RoleName.FINANCE_ANALYST) -> AgentRequest:
    return AgentRequest(username="finance", role=role, is_active=True, question=question)


async def test_n05_passes_similar_examples_to_n06_and_records_their_ids() -> None:
    examples = library()

    async def load() -> list[VerifiedExample]:
        return examples

    model = ScriptedModel(
        REVENUE_Q1, sql=[sql_reply(Q1_SQL, ["orders", "order_details"], metrics_used=["revenue"])]
    )
    deps = dataclasses.replace(fake_deps(model), load_verified=load)
    state = await Agent(deps).run(request("What was our total revenue last quarter?"))

    assert state.status is S.ANSWERED
    assert state.verified_examples
    assert state.verified_examples[0].lineage_id == lineage_for("revenue-last-quarter")
    prompt = " ".join(str(m.content) for m in model.calls_by_kind["sql"][0])
    assert "Verified examples" in prompt
    assert "Example 1. Question: What was our total revenue last quarter?" in prompt
    assert state.sql_attempts[0].verified_examples == [str(e.id) for e in state.verified_examples]


async def test_a_library_problem_does_not_fail_the_question() -> None:
    async def broken() -> list[VerifiedExample]:
        raise RuntimeError("database down")

    model = ScriptedModel(REVENUE_Q1, sql=[sql_reply(Q1_SQL, ["orders", "order_details"])])
    deps = dataclasses.replace(fake_deps(model), load_verified=broken)
    state = await Agent(deps).run(request("What was our total revenue last quarter?"))
    assert state.status is S.ANSWERED
    assert state.verified_examples == []
    prompt = " ".join(str(m.content) for m in model.calls_by_kind["sql"][0])
    assert "none" in prompt


def test_an_example_using_an_outdated_metric_definition_is_not_offered() -> None:
    """Step 26 (scenario 9): after revenue was redefined, the old examples kept the old formula."""
    from app.semantic.verified import uses_definition

    old_sql = "SELECT SUM(od.unit_price * od.quantity * (1 - od.discount)) AS revenue FROM orders o"
    assert uses_definition(old_sql, "SUM(od.unit_price * od.quantity * (1 - od.discount))")
    assert not uses_definition(old_sql, "SUM(od.unit_price * od.quantity)")
    case_sql = "SUM(CASE WHEN x THEN od.unit_price * od.quantity * (1 - od.discount) ELSE 0 END)"
    assert uses_definition(case_sql, "SUM(od.unit_price * od.quantity * (1 - od.discount))")
    assert uses_definition("COUNT(DISTINCT cu.customer_id)", "COUNT(DISTINCT c.customer_id)")
