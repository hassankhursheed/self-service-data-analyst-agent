# Decisions log

What was chosen, what was rejected and why. Newest step last.

## Step 1: Project Setup and Standing Rules

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Brief location | Copied the brief to `docs/capstone-brief.pdf` | Keeping it outside the repo | The step names this path as the source of truth. |
| Python 3.12 | uv-managed CPython 3.12 in `.venv` | Python 3.14 / Anaconda 3.13 already on the machine | The rules require 3.12; uv installs it per user without changing the other Pythons. `requires-python` is pinned to 3.12. |
| Packaging | `pyproject.toml` with hatchling, `dev` extra, editable install | `requirements.txt`; Poetry | One file holds dependencies and tool config; no extra tool required to install. |
| Password hashing | `argon2-cffi` | `passlib` | passlib is unmaintained, breaks with newer bcrypt and relies on the `crypt` module removed in Python 3.13. |
| Charts | Plotly | Matplotlib | Plotly figures serialize to JSON, so the API can return a chart spec and Streamlit renders it interactively. |
| Settings | pydantic-settings; priority env vars > `.env` > `config/app.yaml` > defaults | Everything in `.env`; TOML/JSON config | Secrets stay in the environment; non-secret settings are versioned and readable. |
| Secrets | `SecretStr`, required at startup; tests guard that YAML has no secret fields and `.env.example` lists every env variable | Optional secrets with defaults | Fails fast on missing secrets and keeps values out of logs and reprs. |
| Database settings | Two DSNs: `APP_DATABASE_URL` (app role) and `ANALYTICS_DATABASE_URL` (read-only role) | One DSN with role switching | Brief section 27 requires separate database users; the agent process never holds write credentials. |
| LangSmith variables | Standard SDK names (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`), tracing off by default | Custom names | One variable serves both our settings and the SDK; nothing is sent until enabled. |
| LLM provider | Deferred; only a generic `LLM_API_KEY` slot | Adding a provider package now | Not part of this step and not yet decided. |
| Lint and types | Ruff (incl. ANN, S, PT, ASYNC rules), ruff format, mypy strict with the pydantic plugin | Black + flake8 + isort | One fast tool; ANN enforces "type hints everywhere". |
| Tests | pytest with importlib import mode, pytest-asyncio auto mode, `integration` marker | Default prepend import mode | Avoids test module name clashes; ready for async tests. |
| Git | Initialized the repo on branch `main` | `master` | Matches the GitHub default. |
