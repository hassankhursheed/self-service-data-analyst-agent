"""Step 25: the Railway variable blocks match the settings the app reads."""

import itertools

from app.core.config import Settings
from app.db.setup.users import load_test_users
from scripts.railway_env import api_variables, block, demo_variable, ui_variables


def counter() -> object:
    numbers = itertools.count()
    return lambda size: f"s{next(numbers)}x{size}"


def test_api_block_has_every_setting_with_fresh_values_and_db_references() -> None:
    values = api_variables(counter())  # type: ignore[arg-type]
    assert values["APP_ENV"] == "production"
    assert values["API_HOST"] == "::"
    assert values["API__TRUST_FORWARDED_FOR"] == "true"
    assert values["POSTGRES_HOST"] == "${{Postgres.RAILWAY_PRIVATE_DOMAIN}}"
    assert values["APP_DATABASE_URL"].startswith("postgresql+asyncpg://app_rw:s0x24@")
    assert values["ANALYTICS_DATABASE_URL"].startswith("postgresql+asyncpg://analytics_ro:s1x24@")
    assert len({v for k, v in values.items() if k.startswith("DEMO_PASSWORD_")}) == len(
        load_test_users().users
    )  # each demo account gets its own password
    assert values["LLM_API_KEY"].startswith("REPLACE_")


def test_variable_names_are_the_ones_settings_read() -> None:
    fields = {name.upper() for name in Settings.model_fields}
    for name in api_variables():
        if name.startswith(("RAILWAY_", "API_HOST", "API__", "LANGSMITH_")) or name == "PORT":
            continue
        assert name in fields, name
    assert demo_variable("sales.europe") == "DEMO_PASSWORD_SALES_EUROPE"


def test_ui_block_points_at_the_private_api_address() -> None:
    assert ui_variables()["API_BASE_URL"] == "http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000"
    # The health check port (PORT) is the port the API listens on and the UI calls.
    assert ui_variables()["API_BASE_URL"].endswith(":" + api_variables()["PORT"])
    assert block({"A": "1", "B": "2"}) == "A=1\nB=2"
