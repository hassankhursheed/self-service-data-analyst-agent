"""Step 26 extra: alerts are stored when a threshold is passed, once per cooldown."""

import datetime as dt
import json
from collections.abc import Iterator

import psycopg
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.checkpoint import checkpoint_serializer
from app.api.main import create_app
from app.core.config import AlertsConfig, AlertThresholds, Settings
from app.db.session import create_app_engine, create_session_factory
from app.services.alerts import AlertService, AlertType
from scripts.seed import SeedSummary
from tests.fakes import ScriptedModel, fake_deps
from tests.integration.test_api import assert_error, login, running

pytestmark = pytest.mark.integration
MARK = "alerts-test"


@pytest.fixture
def failed_logins(owner_conn: psycopg.Connection, seeded: SeedSummary) -> Iterator[None]:
    row = owner_conn.execute("SELECT COALESCE(max(id), 0) FROM app.alerts").fetchone()
    first_new = (row[0] if row else 0) + 1
    for _ in range(2):
        owner_conn.execute(
            "INSERT INTO app.audit_log (event_type, details) VALUES ('login_failed', %s)",
            (json.dumps({"test": MARK}),),
        )
    yield
    owner_conn.execute("DELETE FROM app.audit_log WHERE details->>'test' = %s", (MARK,))
    owner_conn.execute("DELETE FROM app.alerts WHERE id >= %s", (first_new,))


def config(cooldown: int = 0) -> AlertsConfig:
    return AlertsConfig(
        enabled=True,
        cooldown_minutes=cooldown,
        min_questions_for_failure_rate=1_000_000,  # not measured here
        thresholds=AlertThresholds(
            blocked_attempts=1_000_000, failed_logins=1, daily_cost_usd=1_000_000
        ),
    )


async def test_an_alert_is_stored_once_per_cooldown(
    settings: Settings, failed_logins: None
) -> None:
    engine = create_app_engine(settings)
    try:
        sessions = create_session_factory(engine)
        service = AlertService(sessions, config(cooldown=60))
        measured = await service.measure()
        assert AlertType.FAILURE_RATE not in measured  # too few questions to judge
        created = await service.check()
        assert [a.alert_type for a in created] == ["failed_logins"]
        assert created[0].channel == "log"
        assert created[0].sent_at is None
        assert "failed logins" in created[0].message
        assert await service.check() == []  # within the cooldown
        recent = await service.recent(5)
        assert recent[0].id == created[0].id
    finally:
        await engine.dispose()


async def test_slack_delivery_marks_the_alert_sent_and_failures_are_harmless(
    settings: Settings, failed_logins: None
) -> None:
    engine = create_app_engine(settings)
    posts: list[tuple[str, dict[str, str]]] = []

    async def poster(url: str, payload: dict[str, str]) -> None:
        posts.append((url, payload))

    async def broken(url: str, payload: dict[str, str]) -> None:
        raise OSError("network down")

    try:
        sessions = create_session_factory(engine)
        url = "https://hooks.example.test/alerts"
        sent = await AlertService(sessions, config(), slack_webhook_url=url, poster=poster).check()
        assert sent[0].channel == "slack"
        assert sent[0].sent_at is not None
        assert posts[0][0] == url
        assert "failed logins" in posts[0][1]["text"]
        later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=1)
        failed = await AlertService(
            sessions, config(), slack_webhook_url=url, poster=broken, clock=lambda: later
        ).check()
        assert failed[0].sent_at is None  # stored, not sent, no exception
    finally:
        await engine.dispose()


async def test_admins_list_alerts_and_others_cannot(
    settings: Settings, failed_logins: None
) -> None:
    app = create_app(
        settings.model_copy(update={"alerts": config()}),
        agent_deps=fake_deps(ScriptedModel()),
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
    )
    async with running(app) as client:
        await app.state.services.alerts.check()
        admin = await login(client, settings, "admin")
        listing = await client.get("/admin/alerts", params={"limit": 5}, headers=admin)
        assert listing.status_code == 200
        assert listing.json()["items"][0]["alert_type"] == "failed_logins"
        finance = await login(client, settings, "finance")
        assert_error(await client.get("/admin/alerts", headers=finance), 403, "ADMIN_ONLY")
