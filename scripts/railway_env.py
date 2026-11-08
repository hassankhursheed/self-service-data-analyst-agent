"""Print the Railway variables for the API and UI services (docs/deployment.md).

    python -m scripts.railway_env

Prints two blocks to paste into each service's Variables > Raw Editor on Railway, with
new random passwords and signing key. Nothing is written to disk; the output is the only
copy, so keep the demo passwords somewhere safe (a password manager) to share them.
Replace ``LLM_API_KEY`` with the real Mistral key in the dashboard.
"""

import secrets
import sys
from collections.abc import Callable

from app.db.setup.users import load_test_users

DB = "${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}"


def demo_variable(username: str) -> str:
    return "DEMO_PASSWORD_" + username.replace(".", "_").upper()


def api_variables(new: Callable[[int], str] = secrets.token_urlsafe) -> dict[str, str]:
    values = {
        "RAILWAY_DOCKERFILE_PATH": "docker/api.Dockerfile",
        "APP_ENV": "production",
        "API_HOST": "::",
        "API__TRUST_FORWARDED_FOR": "true",
        "POSTGRES_USER": "${{Postgres.PGUSER}}",
        "POSTGRES_PASSWORD": "${{Postgres.PGPASSWORD}}",
        "POSTGRES_DB": "${{Postgres.PGDATABASE}}",
        "POSTGRES_HOST": "${{Postgres.RAILWAY_PRIVATE_DOMAIN}}",
        "POSTGRES_PORT": "5432",
        "APP_DATABASE_URL": f"postgresql+asyncpg://app_rw:{new(24)}@{DB}",
        "ANALYTICS_DATABASE_URL": f"postgresql+asyncpg://analytics_ro:{new(24)}@{DB}",
        "JWT_SECRET_KEY": new(48),
        "LLM_API_KEY": "REPLACE_WITH_YOUR_MISTRAL_KEY",
        "LANGSMITH_TRACING": "false",
    }
    for user in load_test_users().users:
        values[demo_variable(user.username)] = new(12)
    return values


def ui_variables() -> dict[str, str]:
    return {"API_BASE_URL": "http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000", "PORT": "3000"}


def block(values: dict[str, str]) -> str:
    return "\n".join(f"{name}={value}" for name, value in values.items())


def main() -> int:
    print("# api service > Variables > Raw Editor (new random passwords; this is the only copy)")
    print(block(api_variables()))
    print()
    print("# ui service > Variables > Raw Editor")
    print(block(ui_variables()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
