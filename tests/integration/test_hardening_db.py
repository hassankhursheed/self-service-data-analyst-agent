"""Step 24: schema drift detection, pooled lookups and non-blocking password hashing."""

import asyncio
import dataclasses
import threading
from collections.abc import Iterator

import psycopg
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.checkpoint import checkpoint_serializer
from app.agent.deps import app_conninfo, database_semantic_loader
from app.api.main import create_app
from app.core.config import Settings
from app.semantic.catalog import load_semantic_layer_file
from app.semantic.models import ColumnDef, SemanticLayer
from app.semantic.schema_check import SchemaDrift, check_semantic_catalog, check_semantic_schema
from app.semantic.verified import database_verified_loader
from scripts.seed import SeedSummary
from tests.fakes import ScriptedModel, fake_deps
from tests.integration.test_api import login, running

pytestmark = pytest.mark.integration


def with_missing_column(layer: SemanticLayer) -> SemanticLayer:
    shippers = layer.tables["shippers"]
    columns = {**shippers.columns, "phone_number": ColumnDef(description="x", allowed_roles=[])}
    tables = {**layer.tables, "shippers": shippers.model_copy(update={"columns": columns})}
    return layer.model_copy(update={"tables": tables})


@pytest.fixture
def app_conn(settings: Settings, seeded: SeedSummary) -> Iterator[psycopg.Connection]:
    with psycopg.connect(app_conninfo(settings)) as conn:
        yield conn


def test_the_app_role_can_check_the_schema_without_table_privileges(
    app_conn: psycopg.Connection,
) -> None:
    layer = load_semantic_layer_file()
    assert check_semantic_catalog(app_conn, layer) == []
    assert check_semantic_catalog(app_conn, with_missing_column(layer)) == [
        "column shippers.phone_number does not exist"
    ]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("SELECT 1 FROM public.shippers LIMIT 1")


def test_a_renamed_column_is_detected(owner_conn: psycopg.Connection, settings: Settings) -> None:
    """Rename a Northwind column inside a transaction that is always rolled back."""
    layer = load_semantic_layer_file()
    with psycopg.connect(settings.owner_conninfo()) as conn:  # not autocommit
        try:
            conn.execute("ALTER TABLE public.shippers RENAME COLUMN company_name TO company")
            problems = check_semantic_schema(conn, layer)
            catalog = check_semantic_catalog(conn, layer)
        finally:
            conn.rollback()
    assert "column shippers.company_name does not exist" in problems
    assert catalog == ["column shippers.company_name does not exist"]
    assert owner_conn.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'shippers' AND column_name = 'company_name'"
    ).fetchone() == (1,)


async def test_the_api_refuses_to_start_on_schema_drift(settings: Settings) -> None:
    deps = fake_deps(ScriptedModel())
    original = deps.load_semantic

    async def drifted() -> SemanticLayer:
        return with_missing_column(await original())

    app = create_app(
        settings,
        agent_deps=dataclasses.replace(deps, load_semantic=drifted),
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
    )
    with pytest.raises(SchemaDrift, match=r"shippers\.phone_number"):
        async with app.router.lifespan_context(app):
            pass


async def test_per_question_lookups_reuse_pooled_connections(
    settings: Settings, seeded: SeedSummary, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.agent.deps as deps_module
    import app.db.pools as pools
    import app.semantic.verified as verified_module

    created: list[pools.LookupPool] = []

    def recording_pool(conninfo: str, **kwargs: int) -> pools.LookupPool:
        pool = pools.lookup_pool(conninfo, **kwargs)
        created.append(pool)
        return pool

    monkeypatch.setattr(deps_module, "lookup_pool", recording_pool)
    monkeypatch.setattr(verified_module, "lookup_pool", recording_pool)
    load_semantic = database_semantic_loader(settings)
    load_verified = database_verified_loader(app_conninfo(settings))
    for _ in range(5):  # five questions
        await load_semantic()
        await load_verified()
    try:
        assert len(created) == 2  # one pool per loader, not one connection per question
        for pool in created:
            stats = pool.pool.get_stats()
            assert stats["connections_num"] <= 2
            assert stats["requests_num"] == 5
    finally:
        for pool in created:
            pool.close()


async def test_many_questions_at_once_open_the_lookup_pool_only_once(
    settings: Settings, seeded: SeedSummary
) -> None:
    """Found by the Step 26 load test: parallel first use made threads wait 30 s or fail."""
    import time

    load_semantic = database_semantic_loader(settings)
    load_verified = database_verified_loader(app_conninfo(settings))
    started = time.perf_counter()
    results = await asyncio.gather(
        *(load_semantic() for _ in range(20)), *(load_verified() for _ in range(20))
    )
    assert len(results) == 40
    assert time.perf_counter() - started < 10  # far below the 30 s open timeout


async def test_login_hashing_runs_off_the_event_loop(
    settings: Settings, seeded: SeedSummary, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.security import verify_password as original

    threads: list[str] = []

    def spy(hashed: str, password: str) -> bool:
        threads.append(threading.current_thread().name)
        return original(hashed, password)

    monkeypatch.setattr("app.auth.service.verify_password", spy)
    app = create_app(
        settings,
        agent_deps=fake_deps(ScriptedModel()),
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
    )
    async with running(app) as client:
        await login(client, settings, "finance")
    assert threads
    assert threads[0] != threading.main_thread().name
