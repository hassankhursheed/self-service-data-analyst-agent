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

## Step 3: Docker Compose and Northwind Load

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Image | `postgres:16` with a named volume `pgdata` | Bind-mounted data folder | Named volumes are portable and `down -v` resets cleanly. |
| Loading | Mount the dump into `docker-entrypoint-initdb.d` (first start only) | A separate load container | Built into the image; runs once per empty volume. |
| Schema | Northwind stays in `public`, as in the dump | Moving it to a dedicated schema | No edits to the public dump; `app` schema is separate (Step 4). |
| Host port | `5433` by default (`POSTGRES_PORT`) | `5432` | A local PostgreSQL service already uses 5432 on the dev machine. |
| Health check | `pg_isready -h 127.0.0.1` (TCP) | Socket `pg_isready` | During first-start loading PostgreSQL listens only on a socket, so TCP stays unhealthy until data is loaded. |
| Owner settings | `POSTGRES_*` variables shared by Compose and `Settings` | A separate owner DSN | One set of variables for the container and the scripts. |
| Line endings | `.gitattributes` forces LF for `.sql`, `.py`, `.yml` | Relying on `core.autocrlf` | The dump is read inside a Linux container. |
| Integration tests | Marker `integration`; skip automatically when the database is unreachable | Always run | Unit tests stay runnable without Docker. Expected row counts are exact; the two customer-demographics tables are empty in the source dump. |

## Step 4: Application Schema and Migrations

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Migration scope | Alembic `include_name` limited to schema `app`; version table in `app`; `env.py` creates the schema if missing | Default (all schemas) | Autogenerate can never see or drop Northwind tables. |
| Migration driver | Sync psycopg as the owner | Async env | Simpler and reliable for migrations; the app itself uses asyncpg. |
| Allowed values | CHECK constraints generated from `app/core/enums.py` | PostgreSQL ENUM types | CHECKs are easy to change in a migration; code and database share one list. |
| Region codes | CHECK on `user_regions.region_code` | FK to `analytics.sales_regions` | Alembic must not depend on a schema it does not own; the seed step creates `analytics`. |
| One role per user | PK of `user_roles` is `user_id` | Composite PK | Matches the design (one role in the token). |
| JSONB | Only `agent_steps.input_summary/output_summary`, `agent_errors.input_snapshot`, `audit_log.details` | JSONB elsewhere | These hold per-node or per-event data whose shape differs by node or event type; everything else is typed columns. |
| Lists | `text[]` / `uuid[]` for tables used, assumptions, options, synonyms, roles | Child tables | Small, read together, never queried by element in hot paths. |
| Keys | UUID for user-facing rows, `bigint` identity for logs | UUID everywhere | Smaller, faster indexes for high-volume tables. |
| Pool settings | In `config/app.yaml` (`database` section) | Hard-coded | Limits live in config (standing rule 8). |
| ERD | Generated from the models (`scripts/generate_erd.py`) with a test that fails on drift | Hand-maintained diagram | Keeps the design doc and the real schema identical. |

## Step 5: Seed Script, Date Shift, Regions and Test Users

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Shift once | Shift plus a row in `analytics.data_setup`, in one transaction under a table lock; a different configured amount stops the seed | Reloading the dump before every shift (Step 2 plan) | Docker loads the dump once; the metadata row makes re-runs safe without reloading. |
| Shifted columns | Order dates and employee birth/hire dates | Order dates only (the step guide's list) | data-decisions.md (approved in Step 2) shifts every date column, so hire dates stay before orders. |
| Region storage | `analytics.sales_regions`, `analytics.country_region` and two lookup views (`customer_regions`, `order_regions`) | A region column added to Northwind tables | Northwind tables stay unchanged; orders take their customer's region. |
| Config files | `config/regions.yaml`, `config/test_users.yaml`, `config/access_policy.yaml`, each validated by a strict Pydantic model | Constants in Python | Standing rule 8; typos fail with the file and field in the message. |
| Sensitive columns | Listed per table with `visible_to` roles and a reason in `config/access_policy.yaml` | The semantic catalog | The same file drives the secure views (Step 6) and later SQL allow-lists. Added beyond the brief: employee city/region/postal code/country/extension/photo path (parts of the home address), customer contact title/fax/address/postal code, supplier contacts, category pictures. |
| Demo passwords | One variable per user, `DEMO_PASSWORD_<USERNAME>`, hashed with argon2 (`argon2-cffi`) | One shared demo password | Each account can be reset on its own; nothing is stored in config. Re-hash only on change, bumping `token_version`. |
| disabled.user | Has the `finance_analyst` role but `is_active = false` | No role | Proves that login fails because of the disabled flag, not a missing role. |
| Seed entry point | `python -m scripts.seed`, logic in `app/db/setup/` | Everything in the script | Seed parts are importable and tested. |

## Step 6: Database Roles, Row-Level Security and Sensitive Columns

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Agent login | One `analytics_ro` login with session settings `app.user_role` and `app.user_region` | Step 2 design: `agent_login` switching to group roles with `SET LOCAL ROLE` | The step guide asks for one `analytics_ro` role and secure views; the design docs are updated. |
| Column hiding | One schema of views per role (`sales_ro`, `finance_ro`, `operations_ro`) built from the access policy | Column grants on base tables | Column visibility differs per role while the login is shared; views also keep the agent off raw tables. |
| Row filtering | Region filter inside `security_barrier` views ("RLS through views") | RLS policies on base tables | `analytics_ro` has no rights on base tables, so policies there would never apply; owner-owned views are the single enforcement point. |
| Fail closed | Every view checks `current_setting('app.user_role', true)`; sales views also check the region | Defaults | Missing settings return zero rows; another role's schema returns zero rows. |
| Scope tampering | `EXECUTE` on `set_config` revoked from `PUBLIC`; queries sent as prepared statements (one statement only); settings set with `SET LOCAL` from enum values | Relying on later SQL validation only | The database itself stops a query from changing its own role or region. |
| Least privilege | `CONNECT`/`TEMP` revoked from `PUBLIC`; no rights on `public`, `analytics`, `app` for `analytics_ro`; `app_rw` only on `app` (default privileges for new tables), not on `alembic_version` | Default PostgreSQL privileges | Brief §12 and §27: no DML, DDL, temp tables or function creation for the agent. |
| Timeouts | `SET LOCAL statement_timeout` per query, a role-level backstop, and a client-side `asyncio.timeout` | One timeout | A forgotten per-query timeout still cannot run forever. |
| Row limit | Cursor fetch of `row_limit + 1` rows with a `truncated` flag | Rewriting the SQL with LIMIT here | SQL rewriting belongs to validation (a later step); the cursor caps memory now. |
| Driver | asyncpg through the SQLAlchemy pool, raw connection for prepare/cursor | SQLAlchemy `text()` | `text()` treats `:name` in agent SQL as bind parameters; prepared statements also block multi-statement input. |
| `app.roles.db_role` | Stores the view schema name | A new column | Same meaning (the role's database scope), no migration needed. |

## Step 7: Semantic Layer

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Source of truth | `config/semantic/semantic_layer.yaml` (versioned), synced into `app.semantic_catalog` and `app.metric_definitions` | Database only; prompt text | Reviewable in git; the database copy is what the agent reads and records by version. |
| Retrieval | Keyword and synonym phrase matching on normalised tokens (lower case, simple singular), then the shortest join path between matched tables, then role filtering | Vector search | The vocabulary is small and closed (8 tables, about 50 columns, 9 metrics, explicit synonyms), so exact phrases are predictable, explainable and testable. Vector search would add a model and fuzzy matches that could pull in tables the question never mentioned. Revisit only if evaluation shows misses that synonyms cannot fix. |
| Role filtering | Applied inside the retriever before anything is returned; a test also checks that the YAML never allows more than the access policy | Filtering in the prompt | A role can never receive an object it may not use. |
| Sync | Same version: upsert in place and delete removed objects; new version: older rows deactivated, not deleted | Delete and reinsert | Safe to run twice; old versions stay for audit. |
| `metric_definitions.description` | Added by a second migration | Storing descriptions elsewhere | Metric descriptions are part of the definition the agent reads. |
| Join key name | `condition` | `on` | YAML 1.1 reads `on:` as the boolean `true`. |
| Schema check | `check_semantic_schema` checks every table and column in `information_schema` and runs each metric with `LIMIT 0` | Checking names only | Catches renamed columns inside metric SQL too; the seed refuses to sync a layer that fails it. |

## Step 8: Business Calendar and Date Resolution

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Reference date | `config/calendar.yaml` (2025-05-06), synced into `app.business_calendar_config` | The real current date; the brief's example 2025-12-31 | Repeatable answers and evaluation; 2025-05-06 is the last order date after the shift. |
| "Last X" | The complete period just before the current one | "Last 3 months" as a rolling window | One rule for all periods; the brief's own example date gives "last quarter" = Q3 2025, which the docs and a test show. |
| "Last N days" | Rolling and including business today | Excluding today | Matches the usual reading of "the last 7 days"; documented with an example. |
| Future periods | Cut at business today and labelled "(to date)"; periods starting after it are unresolved | Returning empty future ranges | There is no data after business today; the user should be told, not shown zeros. |
| Named month/quarter without a year | Most recent one that has started; the assumption is returned | Asking every time | Brief §14: answer minor assumptions but state them. |
| Fiscal year naming | Named after the calendar year it ends in; plain years stay calendar years | Named after the start year | Common convention; identical while the fiscal year starts in January. |
| Parser | Ordered regular expressions over a normalised phrase, no LLM and no date library | dateparser / LLM date parsing | Deterministic, fully unit-tested, and never falls back to the real date. Slash dates are rejected as ambiguous. |
| Result type | `DateRange` or `UnresolvedPeriod` (discriminated by `status`) | Exceptions or None | The agent can branch on `status` and use the reason in a clarifying question. |

## Step 9: SQL Safety Validator

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Parser | sqlglot (PostgreSQL dialect) parse tree for every check; `final_sql` regenerated from the tree without comments | Regex checks; passing the original text through | Parsing sees hidden statements, CTEs and subqueries; regenerating means only what was checked runs. |
| Functions | Allow-list in `config/sql_policy.yaml` (sqlglot function keys) | Deny-list of known dangerous functions | Fails safe: an unknown or forgotten function is blocked. Cost: new harmless functions must be added to config. |
| Real-date functions | Blocked with their own code `REAL_DATE_FUNCTION` | Allowing `now()` / `current_date` | Answers must use the business reference date (Step 8). |
| Column allow-list | Built from the semantic layer per role; columns resolved with sqlglot `qualify` | Checking only the select list; using the database views as the list | Catches hidden columns through aliases, subqueries, CTEs, `WHERE` and `ORDER BY`; stricter than the views (undescribed columns are refused). |
| `SELECT *` | Expanded to the role's allowed columns | Rejecting `*` | Common in generated SQL; expansion keeps it useful while making leaks impossible. |
| Qualified table names | Always blocked (`SCHEMA_QUALIFIED`) | Allowing the user's own view schema | The executor sets `search_path`; any schema name is either redundant or an attempt to reach another schema. |
| Set operations | `UNION` / `INTERSECT` / `EXCEPT` of selects allowed | Blocking them | Still one read-only statement; every branch is checked. |
| `reg*` casts | Blocked as `SYSTEM_CATALOG` | Allowing all casts | `'name'::regclass` reads the catalog. |
| LIMIT | Default 200 added, maximum 1000 enforced, `LIMIT ALL` capped, non-literal and `FETCH FIRST` blocked | Wrapping the query in an outer `SELECT ... LIMIT` | Keeps the SQL readable and the limit checkable. |
| Reason codes | One `BlockReason` enum with one user message each | Free-text reasons | Stable codes for `blocked_queries` and the dashboard; a test enforces a message per code. |
| Question check | Separate `validate_question` (trimmed, empty and too long rejected; limit in config) | Inside the SQL validator | It runs before any LLM call (N-02), long before SQL exists. |

## Frontend technology (decided before Step 10)

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| User interface | Next.js (React, App Router) + TypeScript + Tailwind CSS in `ui/`, talking only to the FastAPI service | Streamlit (listed in Step 1) | User decision: a modern, polished, responsive UI. Allowed by brief §5 ("a small React app"). Next.js server routes keep the access token in an httpOnly cookie. `streamlit` was removed from the Python dependencies. |

## Step 10: LLM Client, Retries, Timeouts and Budgets

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Provider | Mistral (`langchain-mistralai`) through LangChain `init_chat_model`; provider and model in `config/llm.yaml` | Hard-wiring one SDK; LiteLLM now | The step guide's default; `init_chat_model` lets the provider change in config without code. LiteLLM fallback stays a recommended extra. |
| Model version | `mistral-small-latest` for development | Pinning now | Evaluation (brief §24) needs a fixed dated version; it is pinned in the evaluation step and recorded with each run. |
| Retries | Our own loop: up to 3 attempts, backoff 1 s, 2 s, ... capped at 8 s; LangChain/provider retries set to 0 | Provider SDK retries | One policy in one place; only timeouts, 408/409/425/429/5xx and connection errors are retried. 400/401/403/404/422 and unknown errors fail at once. |
| Timeout | `asyncio.timeout` per attempt plus the model's own HTTP timeout, from config | Model timeout only | The client-side timeout also covers hangs outside the HTTP call; each attempt gets the full time. |
| Budget | Per-question `BudgetTracker`: checks before each call that used tokens + estimated input + `max_tokens` stays within the token and cost limits; records real usage from the reply | Checking after the call | A call that could exceed the budget never reaches the provider. |
| Cost | Estimated from `pricing` in config (USD per million tokens) | Live price lookup | Simple and repeatable; prices must be checked against the provider's list. |
| Errors | `app/core/errors.py`: `RetryableError`, `NonRetryableError`, `BudgetExceeded`, `DbTimeout`, `ValidationBlocked`, each with a code and a safe user message | Raw provider exceptions | Later steps map errors to statuses and AgentErrors consistently. |
| Prompts | YAML files `config/prompts/<name>/<version>.yaml` with declared input variables (checked against the template) and `name@version` refs; versions chosen in `llm.yaml` | Long strings in Python | Standing rule 8; versions are recorded with each run. |
| Tracing | LangSmith only through `LANGSMITH_*` environment variables, read by LangChain | Enabling tracing in code | Brief §27: configuration by environment only; off by default. |

## Step 11: LangGraph State, Transitions, Intake and Guardrails

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| State | One Pydantic `AgentState`; `steps` appended through a LangGraph reducer | TypedDict state; one big dict | Validated types between nodes (standing rule 3); every node's record is kept. |
| Transitions | Table `ALLOWED` plus `check_transition` in a shared node wrapper; routing only from `ROUTES` | Free conditional edges per node | A node cannot skip validation or loop freely (brief §11); tests prove routes and the table agree. |
| Errors in nodes | Wrapper turns unexpected errors into `FAILED` with a safe message; `IllegalTransition` is raised | Letting exceptions escape; swallowing illegal transitions | Users never see stack traces (brief §22); an illegal transition is a bug and must surface. |
| N-01 | Rejects disabled users, users with no role, admins and sales managers without a region before any LLM call | Rejecting only no-role users | Brief §2: admins have no business questions by default; a region-scoped role without a region has no data. |
| N-02 outcome | Empty, too long, off-topic: REJECTED; injection, data change, personal data: BLOCKED | Everything BLOCKED | REJECTED = not a business question; BLOCKED = safety event counted on the dashboard. |
| Scope-widening phrases | Flagged and continued with a notice; the database enforces the region | Blocking them (Step 11 plan) | Brief §13 and scenario 15 require the "all regions" prompt to still return only the user's region. Found while building; documented in docs/guardrails.md. |
| Personal data | Role-aware rules tied to columns in the access policy | Blocking any contact-related words | Sales managers may see their customers' contacts; operations may see supplier contacts. |
| Classifier | Rules only, from `config/guardrails.yaml` | Small LLM classifier | Free, deterministic, testable; add a classifier only if evaluation shows misses. |
| Data-change requests | Blocked at N-02 and again by the SQL validator | Only the validator | Cheaper (no LLM call) and gives a clear reason early. |
| Commit messages | Short descriptive messages without "Step N" (user request); older messages rewritten locally | `Step N: <title>` | User preference; CLAUDE.md rule 9 updated. |
