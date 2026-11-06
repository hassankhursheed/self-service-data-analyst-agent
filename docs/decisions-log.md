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

## Step 2: Design Checkpoint Documents

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Date shift | +27 whole years on all date columns | +27 years plus months; +28 years | Keeps months, quarters and seasonality; +28 would put orders past the reference date. |
| Business reference date | 2025-05-06 (last order date after the shift) | 2025-12-31 (brief example) | 2025-12-31 would leave May to December 2025 empty. |
| "Last quarter" rule | Most recent complete period before the current one | Calendar quarter before the one containing today, regardless of completeness (same result here, but undefined for partial data) | Repeatable, explainable answers; always stated in the answer. |
| Region mapping | Europe = 15 European countries; Americas = USA, Canada, Mexico; Rest of World = Brazil, Argentina, Venezuela | Continent mapping (empty Rest of World); adding fictional customers | Every regional test user has real data, so isolation can be proven. |
| Schemas | `public` (Northwind), `analytics` (region map), `app`, `checkpoints` | Separate databases | One database keeps RLS lookups simple; schemas separate ownership and grants. |
| Access control | One read-only login (`agent_login`) switching with `SET LOCAL ROLE` to `sales_ro`/`finance_ro`/`operations_ro`, plus `SET LOCAL app.region`; RLS on customers, orders, order_details; column grants for sensitive columns | One login per business role; secure views per role | One pooled login is simpler; `SET LOCAL` cannot leak across pooled connections; column grants make hidden columns fail in the database too. |
| One role per user | Unique `user_roles.user_id` | Many roles per user | The token carries one role; access rules stay unambiguous. |
| Agent outcomes in the API | `200` with `status` (`BLOCKED`, `FAILED`, `CLARIFICATION_NEEDED`) | HTTP 4xx/5xx for agent outcomes | A blocked query is a valid answer to show the user; HTTP errors stay for request problems. |
| Extra endpoints | `PATCH /admin/users/{id}`, `POST /admin/users/{id}/reset-password`, `PATCH /admin/verified-queries/{id}`, `POST /admin/feedback/{id}/eval-case`, `GET /admin/eval/runs/{id}` | Overloading `POST` with action flags | §8, §16 and §20 require these actions; separate endpoints are clearer and easier to test. |
| Statement timeout | `FAILED` with a clear message, no repair | Treating a timeout as repairable | Repairing usually cannot make a slow query fast; scenario 20 wants a clear message. |
| Login errors | Same `INVALID_CREDENTIALS` for unknown user, wrong password, disabled user | Distinct messages | Does not reveal which usernames exist. |
| Diagram check | Rendered every Mermaid block with `mmdc` (Mermaid CLI 11, installed outside the repo) | Visual check only | Proves the syntax renders, as the step requires. |
