"""Step 17: login, token checks, revocation and admin user management (real database)."""

import datetime as dt
from collections.abc import AsyncIterator
from dataclasses import dataclass

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.conversations import ConversationService
from app.agent.graph import Agent
from app.auth.models import AuthenticatedUser
from app.auth.service import AuthService, InvalidCredentials
from app.auth.tokens import InvalidToken, TokenExpired, TokenService
from app.core.config import Settings
from app.core.enums import QuestionStatus, RegionCode, RoleName
from app.db.session import create_app_engine, create_session_factory
from app.services.users import (
    InvalidUserInput,
    NotAllowed,
    UserAdminService,
    UsernameTaken,
)
from scripts.seed import SeedSummary
from tests.fakes import ScriptedModel, fake_deps, intent, sql_reply
from tests.integration.test_sql_path_db import real_executor

pytestmark = pytest.mark.integration
NEW_PASSWORD = "new-demo-password-123"


@dataclass
class Services:
    auth: AuthService
    users: UserAdminService
    tokens: TokenService
    sessions: object


@pytest.fixture
async def services(
    settings: Settings, seeded: SeedSummary, owner_conn: psycopg.Connection
) -> AsyncIterator[Services]:
    engine = create_app_engine(settings)
    sessions = create_session_factory(engine)
    tokens = TokenService(settings.jwt_secret_key.get_secret_value(), settings.auth)
    started = dt.datetime.now(dt.UTC)
    yield Services(AuthService(sessions, tokens), UserAdminService(sessions, settings.auth), tokens,
                   sessions)  # fmt: skip
    await engine.dispose()
    owner_conn.execute("DELETE FROM app.users WHERE username LIKE 'test.%'")
    owner_conn.execute("DELETE FROM app.audit_log WHERE occurred_at >= %s", (started,))
    # Undo password resets and disables done to seeded accounts.
    from scripts.seed import run_seed

    run_seed(settings)


def password(settings: Settings, username: str) -> str:
    secret = settings.demo_password(username)
    assert secret is not None
    return secret.get_secret_value()


async def admin(services: Services, settings: Settings) -> AuthenticatedUser:
    login = await services.auth.login("admin", password(settings, "admin"))
    return login.user


# --- scenario 1: login ------------------------------------------------------------------


async def test_correct_login_returns_a_token_and_the_identity(
    services: Services, settings: Settings, owner_conn: psycopg.Connection
) -> None:
    result = await services.auth.login("sales.europe", password(settings, "sales.europe"))
    assert result.user.role is RoleName.SALES_MANAGER
    assert result.user.region is RegionCode.EUROPE
    assert result.expires_in == settings.auth.access_token_minutes * 60
    identity = await services.auth.authenticate(result.access_token)
    assert identity.username == "sales.europe"
    logged = owner_conn.execute(
        "SELECT count(*) FROM app.audit_log WHERE event_type = 'login' AND actor_user_id = %s",
        (result.user.user_id,),
    ).fetchone()
    assert logged is not None
    assert logged[0] >= 1


@pytest.mark.parametrize(
    ("username", "wrong"),
    [("finance", True), ("disabled.user", False), ("nobody.here", True)],
)
async def test_wrong_password_disabled_and_unknown_users_are_refused(
    services: Services,
    settings: Settings,
    owner_conn: psycopg.Connection,
    username: str,
    wrong: bool,
) -> None:
    secret = "definitely-wrong-password" if wrong else password(settings, username)
    with pytest.raises(InvalidCredentials) as err:
        await services.auth.login(username, secret)
    assert err.value.user_message == "The username or password is not correct."
    failed = owner_conn.execute(
        "SELECT count(*) FROM app.audit_log WHERE event_type = 'login_failed' AND target_id = %s",
        (username,),
    ).fetchone()
    assert failed is not None
    assert failed[0] >= 1


# --- scenario 2: tokens ------------------------------------------------------------------


async def test_expired_and_invalid_tokens_are_refused(
    services: Services, settings: Settings
) -> None:
    user = (await services.auth.login("finance", password(settings, "finance"))).user
    expired = services.tokens.issue(
        user.user_id, 0, now=dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    )
    with pytest.raises(TokenExpired):
        await services.auth.authenticate(expired)
    for bad in ("", "garbage", "a.b.c"):
        with pytest.raises(InvalidToken):
            await services.auth.authenticate(bad)


async def test_role_and_region_come_from_the_database_on_every_call(
    services: Services, settings: Settings
) -> None:
    login = await services.auth.login("sales.other", password(settings, "sales.other"))
    actor = await admin(services, settings)
    await services.users.assign_role(
        actor, login.user.user_id, RoleName.SALES_MANAGER, RegionCode.AMERICAS
    )
    identity = await services.auth.authenticate(login.access_token)  # same, unchanged token
    assert identity.region is RegionCode.AMERICAS


# --- revocation --------------------------------------------------------------------------


async def test_a_disabled_users_old_token_stops_working(
    services: Services, settings: Settings
) -> None:
    actor = await admin(services, settings)
    created = await services.users.create_user(
        actor, username="test.temp", display_name="Temp", password=NEW_PASSWORD,
        role=RoleName.FINANCE_ANALYST,
    )  # fmt: skip
    token = (await services.auth.login("test.temp", NEW_PASSWORD)).access_token
    assert (await services.auth.authenticate(token)).username == "test.temp"
    await services.users.set_active(actor, created.id, False)
    with pytest.raises(InvalidToken):
        await services.auth.authenticate(token)
    with pytest.raises(InvalidCredentials):
        await services.auth.login("test.temp", NEW_PASSWORD)
    await services.users.set_active(actor, created.id, True)
    with pytest.raises(InvalidToken):  # re-enabling does not revive the old token
        await services.auth.authenticate(token)


async def test_password_reset_revokes_old_tokens(services: Services, settings: Settings) -> None:
    actor = await admin(services, settings)
    created = await services.users.create_user(
        actor, username="test.reset", display_name="Reset", password=NEW_PASSWORD,
        role=RoleName.OPERATIONS_MANAGER,
    )  # fmt: skip
    token = (await services.auth.login("test.reset", NEW_PASSWORD)).access_token
    await services.users.reset_password(actor, created.id, "another-password-456")
    with pytest.raises(InvalidToken):
        await services.auth.authenticate(token)
    with pytest.raises(InvalidCredentials):
        await services.auth.login("test.reset", NEW_PASSWORD)
    assert (
        await services.auth.login("test.reset", "another-password-456")
    ).user.username == "test.reset"


# --- admin service -----------------------------------------------------------------------


async def test_only_admins_manage_users(services: Services, settings: Settings) -> None:
    finance = (await services.auth.login("finance", password(settings, "finance"))).user
    with pytest.raises(NotAllowed):
        await services.users.create_user(
            finance, username="test.sneaky", display_name="x", password=NEW_PASSWORD,
            role=RoleName.ADMIN,
        )  # fmt: skip
    with pytest.raises(NotAllowed):
        await services.users.list_users(finance)


async def test_user_input_is_validated(services: Services, settings: Settings) -> None:
    actor = await admin(services, settings)
    with pytest.raises(InvalidUserInput):
        await services.users.create_user(actor, username="test.a", display_name="a",
                                         password="short", role=RoleName.FINANCE_ANALYST)  # fmt: skip  # noqa: E501
    with pytest.raises(InvalidUserInput):
        await services.users.create_user(actor, username="test.b", display_name="b",
                                         password=NEW_PASSWORD, role=RoleName.SALES_MANAGER)  # fmt: skip  # noqa: E501
    with pytest.raises(InvalidUserInput):
        await services.users.create_user(actor, username="Bad Name", display_name="c",
                                         password=NEW_PASSWORD, role=None)  # fmt: skip
    with pytest.raises(UsernameTaken):
        await services.users.create_user(actor, username="finance", display_name="d",
                                         password=NEW_PASSWORD, role=None)  # fmt: skip
    with pytest.raises(InvalidUserInput):
        await services.users.set_active(actor, actor.user_id, False)


async def test_user_management_actions_are_audited(
    services: Services, settings: Settings, owner_conn: psycopg.Connection
) -> None:
    actor = await admin(services, settings)
    created = await services.users.create_user(
        actor, username="test.audited", display_name="Audited", password=NEW_PASSWORD,
        role=RoleName.FINANCE_ANALYST,
    )  # fmt: skip
    await services.users.set_active(actor, created.id, False)
    await services.users.set_active(actor, created.id, True)
    await services.users.reset_password(actor, created.id, "yet-another-password-1")
    await services.users.assign_role(actor, created.id, RoleName.OPERATIONS_MANAGER)
    events = [r[0] for r in owner_conn.execute(
        "SELECT event_type FROM app.audit_log WHERE target_id = %s ORDER BY id",
        (str(created.id),),
    ).fetchall()]  # fmt: skip
    assert events == [
        "user_created",
        "user_disabled",
        "user_enabled",
        "password_reset",
        "role_assigned",
    ]
    listed = {u.username for u in await services.users.list_users(actor)}
    assert {"test.audited", "finance", "sales.europe"} <= listed


# --- scenario 24 -------------------------------------------------------------------------


async def test_new_user_with_a_region_immediately_sees_only_that_region(
    services: Services,
    settings: Settings,
    analytics_engine: AsyncEngine,
    owner_conn: psycopg.Connection,
) -> None:
    actor = await admin(services, settings)
    await services.users.create_user(
        actor, username="test.nordics", display_name="Nordics Sales", password=NEW_PASSWORD,
        role=RoleName.SALES_MANAGER, region=RegionCode.EUROPE,
    )  # fmt: skip
    login = await services.auth.login("test.nordics", NEW_PASSWORD)
    user = await services.auth.authenticate(login.access_token)
    assert (user.role, user.region) == (RoleName.SALES_MANAGER, RegionCode.EUROPE)

    sql = (
        "SELECT c.country, count(*) AS orders FROM orders o "
        "JOIN customers c ON c.customer_id = o.customer_id GROUP BY c.country"
    )
    model = ScriptedModel(
        intent(summary="Orders by country", metric="number_of_orders", time_phrase=None,
               grouping="country"),
        sql=[sql_reply(sql, ["orders", "customers"], metrics_used=["number_of_orders"])],
    )  # fmt: skip
    service = ConversationService(
        Agent(fake_deps(model, real_executor(analytics_engine))),
        services.sessions,  # type: ignore[arg-type]
    )
    state = await service.ask(user, "How many orders per country?")
    assert state.status is QuestionStatus.ANSWERED
    assert state.execution is not None
    europe = {
        str(r[0])
        for r in owner_conn.execute(
            "SELECT country FROM analytics.country_region WHERE region_code = 'EUROPE'"
        ).fetchall()
    }
    countries = {str(r[0]) for r in state.execution.rows}
    assert countries
    assert countries <= europe
