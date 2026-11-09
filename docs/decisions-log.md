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

## Step 12: Intent, Ambiguity and Clarification

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Structured output | Prompted JSON parsed and validated by Pydantic (`ainvoke_structured`), code fences tolerated | Provider tool-calling / `with_structured_output` | Works the same with any provider and with scripted test models; the validation error is sent back for the one regeneration. |
| Who decides | The model describes the question; `decide()` applies fixed rules from config | Letting the model decide when to ask | Deterministic and testable; the model cannot talk itself out of asking. |
| Blocking parts | Metric, entity, grouping always ask; time range and top N become stated defaults unless the agent is asking anyway | Asking about every missing part | Brief §14: ask when the answer would change; state minor assumptions ("this year", top 10). |
| One combined question | Everything missing in one question with 2-4 options; model question used only when it has 2-4 options, otherwise a template | Several questions in a row | One clear question per round (brief §14). |
| Rounds | 1, a second only if the reply is still unclear; then `FAILED` with guidance | Unlimited rounds; guessing after round 2 | No loops and no silent guessing. |
| Pause | LangGraph `interrupt` in N-04, resume with `Command(resume=reply)`; N-04 hands back to N-03 | Ending the run and starting a new one | The same thread keeps the state, the audit trail and the budget. |
| Checkpointer | In-memory for now | PostgreSQL now | Step 15 adds the PostgreSQL checkpointer and user-scoped threads. |
| Node wiring | `AgentDeps` (LLM client, configs, calendar, semantic layer) passed when the graph is built | Globals inside nodes | Tests swap in a scripted model; no real LLM in unit tests. |
| Budget across nodes | `BudgetTracker` continues from the usage already in the state | A new budget per node | The token and cost limit is per question (brief §22). |

## Step 13: Context Retrieval, SQL Generation, Execution and Repair

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Semantic layer source | Loaded from the database copy for every question (file in unit tests) | Loading once at startup | Scenario 9: a changed definition is used without code changes or a restart; about 80 rows, cheap. |
| Context check | `tables_used` / `metrics_used` outside the retrieved context count as malformed (regenerated once) | Trusting the model's lists | Keeps the model inside what the role was shown; the validator still checks the real SQL. |
| Low confidence | Flag when the model says `low` or its period differs from the resolved one | Model's word only | A wrong period is the most likely silent error. |
| What runs | Only the validator's `final_sql`, through `run_readonly` with the user context from the state | Running the model's SQL | One enforced path: validation, then the read-only role and session settings. |
| Database refusal | `BLOCKED` (`DATABASE_REFUSED`), new transition `VALIDATED -> BLOCKED` | Repairing it | A refusal means a safety rule fired; it must not be "repaired" around. |
| Timeout | `FAILED` with a clear message, no repair | Repairing timeouts | Repair rarely makes a slow query fast (scenario 20). |
| Connection errors | Retried with backoff (`db_connect_attempts`), then `FAILED` | Crashing; retrying query errors | Brief section 22: survive connection failures; query errors go to repair instead. |
| Repair loop | N-09 sends the SQL that ran plus the error, returns via `REPAIRING` to N-07; max 2 repairs | Executing repaired SQL directly | Repaired SQL is always validated again; no loops beyond the limit. |
| Executor injection | `AgentDeps.executor` (default: pooled analytics engine) | Calling `run_readonly` inside the node | Unit tests use a fake executor; integration tests use the real role. |
| Checkpoint serializer | Allow-list of the app's state types, collected from `AgentState` | Default (warns), or allow everything | LangGraph will refuse unregistered types; an explicit list avoids restoring arbitrary classes. |
| Region synonyms | `region` and `sales region` map to `customers.country` in the semantic layer | No synonym | Found by the scenario 15 test: region questions need the customer country. |

## Step 14: Grounded Answers and Charts

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| What the LLM sees | First 20 rows (config), role-allowed columns only, plus the SQL and period | The whole result | Brief §17 and §27: summarise top rows only and send no more data than needed. |
| Grounding | Every number in the explanation must match a result value (rounding, separators, k/million), a derived percentage (value, fraction, share of column total, change between two values) or a context number (row count, top N, question, period) | Trusting the model; exact string matching | Catches invented numbers while allowing normal formatting; allowances are documented. Model-computed sums are rejected. |
| Ungrounded answer | One regeneration with the bad numbers listed, then a template answer from the rows | Failing the question | The result is correct; only the wording is untrusted, so a plain answer is still useful. |
| LLM failure at N-10 | Template answer, still `ANSWERED` | `FAILED` | Same reason: the rows are already safe and correct. |
| Empty result | Fixed honest message with a suggestion, no LLM call | Asking the model | Nothing to explain; no risk of an invented number (scenario 21). |
| Chart spec | Neutral `{type, x, y, data}` from a pure rule function | Plotly figure JSON | The UI is now React; any chart library can draw a neutral spec. `plotly` removed from the dependencies. |
| Chart rules | Metric card / line / bar / none with limits in config (30 bars, 400 points, 3 series); truncated results get no chart | Letting the model pick | Deterministic and testable (brief §17: simple, documented rules). |
| Response model | `AgentResponse` built from the state with pagination | Returning the raw state | One stable shape for the API (Step 17) and UI; always includes SQL, description, assumptions, period and row count when answered. |

## Step 15: Conversation Memory and Follow-ups

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Checkpointer | `AsyncPostgresSaver` with a psycopg pool as `app_rw`, `search_path=checkpoints`; tables created by the seed as owner | Calling `setup()` at runtime; storing checkpoints in `public` or `app` | `app_rw` needs no DDL rights; checkpoints are kept apart from Northwind and from Alembic-managed tables. |
| Thread ID | `user:<user id>:conversation:<conversation id>`, built only after an ownership check | The conversation ID alone | Two layers: the ownership check, and a thread ID that differs per user even for a guessed conversation ID. |
| Not found | `ConversationNotFound` for another user's conversation | `403 Forbidden` | Does not reveal that the conversation exists. |
| Per-question state | Fresh state for every question with all fields passed explicitly; `steps` without a reducer | Reusing the thread's previous state | LangGraph only overwrites keys that are present; a new question must not inherit status, SQL or steps (found by a test: N-01 saw `ANSWERED -> RECEIVED`). |
| Follow-up context | A short history (5 turns: question, standalone question, status, SQL, period) shown to the intent prompt (v2) | Re-running earlier SQL; full previous state | Brief §18: earlier SQL never skips validation; the model rewrites a standalone question and everything runs again. |
| Interpreted question | `interpreted_question` + "Interpreted as: ..." notice, `interpreted_as` in the response | Silent rewriting | The user sees how the follow-up was understood. |
| App tables | `app.conversations` and `app.questions` written by `ConversationService` (app role) | Writing them inside graph nodes | The graph stays storage-agnostic; Step 16 adds runs, steps and audit rows. |
| Windows event loop | Selector loop via the `pytest_asyncio_loop_factories` hook | Proactor (default) | psycopg async does not support the Proactor loop. |
| Validator fix | `AND` / `OR` connector nodes are not checked as functions | — | Found by the Germany follow-up test: sqlglot models `AND`/`OR` as function-like connector nodes, so `WHERE a AND b` was refused as a forbidden function. Regression tests added. |

## Step 16: Audit Log, Error Records and Tracing

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Where audit is written | N-11 through an injected `AuditSink` (database in the app, memory in unit tests), one transaction per run | Writes spread over every node | One place to reconstruct a question; nodes stay storage-free and testable. |
| Failure handling | Catch, log with the correlation ID, `audit_ok = false`, still answer | Failing the question | Brief: audit writes must never break the user's answer. |
| Attempts and executions | Kept in the state (`sql_attempts`, `executions`) and written as `generated_queries` / `query_executions` rows | Only the last SQL | Repairs and their errors must be visible (brief §23). |
| Trace link | Correlation ID = LangSmith root run ID; stored as `langsmith:<project>/runs/<id>` | A separate trace ID | One ID connects the API response, every table and the trace. |
| Masking point | Before the graph (question), on answer-prompt rows, and on every audit write | Masking only in the database | Brief §27: sensitive data must not reach the LLM or traces either; the raw value never enters the system. |
| Masking rules | Regex rules for e-mail, phone, card/bank numbers, IBAN, keys, tokens, passwords; business numbers and dates kept (tested) | Masking all numbers | Questions are full of amounts, years and order IDs that must stay readable. |
| `prompt_version` | Widened to 255 characters (migration) to hold `name@version` for every prompt | Storing only one prompt's version | Runs must record every prompt version used. |
| asyncpg introspection | Role-level `jit = off` and telling asyncpg JIT is off, so it never calls `set_config` | Granting `set_config` back | Found by the audit tests: asyncpg toggles JIT with `set_config` before introspecting `uuid[]`; granting it would let a query change its own region. A test proves `array_agg` results work for `analytics_ro`. |
| Re-run input | `agent_errors.input_snapshot` stores the masked request, clarification answers and thread | Storing the whole state | Enough to re-run (Step 18) without keeping results or secrets. |

## Step 17: Authentication and User Management

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Token contents | `sub` (user ID), `ver` (token version), `iss`, `iat`, `exp`, `jti`; HS256 | Role and region in the token | Brief §8: role and region come from the database for every request, so a role change applies at once and cannot be forged. |
| Revocation | `token_version` bumped on disable and password reset; checked on every request | Token deny-list; very short tokens only | One integer per user; old tokens stop working immediately (brief §8). |
| Login errors | One message for unknown user, wrong password and disabled account; dummy hash verified for unknown users | Distinct errors | No username enumeration by message or timing; the reason is in the audit log. |
| Secret strength | At least 32 characters required in production | No check | A short HMAC key is guessable; development and tests may use shorter keys. |
| Dependencies | `CurrentUser` / `AdminUser` FastAPI dependencies now, used by the API in Step 18 | Writing them with the API | The guide asks for the dependency in this step; it only needs `app.state.auth`. |
| Admin rules | Admin-only service methods; username pattern; password length from config; sales managers need exactly one region; admins cannot disable themselves | Validation only in the API | The same rules apply whatever calls the service (API, scripts, tests). |
| Audit | `login`, `login_failed` (with reason), `user_created`, `user_disabled`, `user_enabled`, `password_reset`, `role_assigned` in `audit_log` | Separate auth log | One audit trail for the monitoring view (brief §8, §23). |
| Shared identity | `AuthenticatedUser` moved to `app/auth/models.py` | Defined in the conversation service | Auth, API and agent use one model. |

## Step 18: FastAPI Endpoints

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| App structure | `create_app(settings, agent_deps=, checkpointer=)` factory; one lifespan opens the engine, PostgreSQL checkpointer, agent and services and closes them | Module-level globals | Tests build an app with a scripted LLM and in-memory checkpointer; production uses the real wiring. |
| Correlation ID | Middleware accepts a valid UUID from `X-Correlation-ID` or creates one; header and every body carry it; passed to the agent as the run ID | Separate request and run IDs | One ID links the HTTP response, audit rows and the LangSmith trace (brief §22). Invalid client values are replaced, not trusted. |
| `/clarify` correlation ID | The response uses the paused question's ID | A new ID per HTTP call | The resumed run is the same question, so header, body, audit and trace match. |
| `/clarify` body | `{conversation_id, answer}` | `{question_id, clarification_id, answer}` (design draft) | One pending clarification per conversation thread; the owner check on the conversation is enough. api-design.md updated. |
| Error shape | `{correlation_id, error: {code, message}}`; status from the stable code; unknown errors become a generic 500 in the middleware | FastAPI default `{detail}`; returning exception text | No stack traces or internal details reach the client (brief §22); the error is logged with the correlation ID. |
| No role / admin on `/ask` | The agent runs (and audits the rejection), then the API returns 403 `NO_ROLE` / `ADMIN_ONLY` | Refusing before the agent | Every refused question still leaves an audit trail. Empty or too-long questions become 400 the same way. |
| Blocked / failed answers | 200 with `status` and a plain message | HTTP errors | Agent outcomes are not request errors (api-design.md). |
| Feedback | Built now: one rating per user and question, updated on resend; only for own questions | Waiting for Step 20 | The endpoint is listed in §19 and the table exists; the review queue comes in Step 20. |
| Re-run | Claims the error (`open` -> `rerun`) atomically, reloads the original user's current role, region and active flag, runs the masked logged question, audits `error_rerun`; 409 if already re-run | Running as the admin; re-using the old identity snapshot | A re-run never gives more access than the user has today, and cannot be triggered twice. |
| Later-step routes | Defined with their final models and return 501 | Leaving them out | The OpenAPI contract is complete for the UI; behaviour arrives in its step. |
| Rate limits | In-memory sliding window: 20 questions per minute per user, 10 logins per minute per IP (config) | Redis; no limits | Enough for one API process; documented as a limitation. |
| CORS | Only the UI origin from `config/app.yaml` (default `http://localhost:3000`); `X-Correlation-ID` exposed | `*` | The browser may only call the API from the UI. |
| Conversation detail | Question list plus the full response of the latest question | Full response for every question | The checkpointer keeps only the latest state per thread; earlier answers are reconstructable from the audit tables later if needed. |
| Region in user models | One `region` field | `regions: [...]` (design draft) | The data model and Step 17 service use one region per sales manager. |

## Step 19: User Interface

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Framework | Next.js 16 (App Router) + React 19 + TypeScript (strict) + Tailwind CSS 4, exact versions pinned, each at least two weeks old | Streamlit; a plain Vite SPA | User decision (polished, responsive UI); server routes let the token stay out of the browser. |
| Token handling | Next.js server routes; token in an `httpOnly`, `SameSite=Strict` (`Secure` in production) cookie; the browser gets only the user | Token in `localStorage`; calling the API from the browser | No script can read the token (XSS cannot steal it); the API is never exposed to the browser and needs no CORS for the UI. |
| Proxy scope | Allow-list of the API paths the UI uses; same-origin JSON required for writes | Forwarding every path | Smallest surface; CSRF protection on top of SameSite. |
| Identity in the header | `GET /auth/me` (new) on every page load | Role stored in a cookie or in local state | A changed role or a disabled account applies immediately and cannot be faked in the browser. |
| Admin pages | Hidden in the navigation, refused by the server-side admin layout, and 403 from the API | Hiding links only | Defence in depth; non-admins never receive admin pages. |
| Admins on Ask | Redirected to the admin pages | Showing the Ask screen with a 403 | Business questions are off for admins (brief §8); a dead screen confuses. |
| Result paging | `GET /conversations/{id}/table` (new) pages the latest question's stored rows | Re-running the query per page; sending all rows | No extra query or LLM call; keeps responses small. |
| Charts | Recharts with theme-aware colours, drawing the API's chart spec | Plotly | Lighter and React-native; the API already chooses the chart type. |
| Docker | `api` and `ui` services in the `app` profile; the API entrypoint swaps the database host in the `.env` URLs to `db:5432`; images run as non-root with health checks; Python versions pinned by `docker/constraints.txt` | Always starting everything; duplicating URLs with passwords in compose | `docker compose up -d` stays database-only for tests; no secrets in compose files. |
| Tests | Vitest + Testing Library: chart choice, outcome messages, clarification, feedback, role-based navigation, proxy token handling, allow-list, CSRF, login cookie | Browser end-to-end tests | Fast and deterministic; the end-to-end checks are done manually with screenshots. |
| Rate limit of logins | Unchanged (per client IP at the API) | Forwarding `X-Forwarded-For` | Behind the UI all logins come from the UI server, so the limit is effectively per UI instance; trusting a client header would let anyone bypass it. Documented. |

## Step 20: Verified Query Library and Feedback Loop

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Similarity | Keyword cosine similarity over token sets (same tokenising as the semantic retriever, small stop-word list), `min_score` 0.4, at most 3 examples (config) | Embeddings and a vector index | The library is tens of short, domain-specific questions; token overlap finds the right one, is deterministic and explainable, and needs no model or service. `similarity()` can be swapped later. |
| Access control for examples | Offered only if enabled, the role is listed, **and** the SQL passes the validator for the user's role against today's semantic layer | Trusting the stored roles only | Examples never bypass access control, even after a role or the semantic layer changes. |
| Saving rules | SQL validated for every allowed role; tables taken from the validator; allowed roles never wider than the metrics' roles; business roles only | Free-form saving | Brief: corrected SQL must pass the validator; a finance-only example must not reach sales. |
| Versioning | Correction = new version in the lineage; one enabled version per lineage (partial unique index); enabling re-validates | Editing in place | History is kept and auditable; runs record which version they used. |
| Seed | 18 examples in `config/verified_queries.yaml`; lineage `uuid5(key)`; only missing lineages are inserted | Re-writing on every seed | Admin corrections and disabled examples survive a re-seed. Every example is checked against the validator and the data. |
| Prompt | `sql_generation` v2 with a "Verified examples" block; follow patterns but use this question's period and filters | Copying example SQL | Dates in examples are illustrations; the resolved period stays authoritative. |
| Failure handling | A library loading problem is logged; the question continues without examples | Failing the question | Examples are guidance, not a dependency. |
| Review list | One `GET /admin/review` merging open not-helpful answers, blocked queries and open failures, newest first | Separate screens only | Brief §16 / guide: one list; the older `/admin/blocked` and `/admin/errors` stay for filtering. |
| Eval cases from feedback | Dataset `review-cases`, key `FB-<feedback id>`, expected SQL validated for the asking user's role; feedback becomes `converted` (409 on repeat) | Writing to the YAML eval file | Cases stay traceable to their feedback; Step 22 decides how datasets are exported. |
| Feedback link | `feedback.run_id` = latest run of the question (migration) | Question only | Guide: feedback is linked to the question and its run. |
| Graph version | 0.5.0 | — | N-05 / N-06 behaviour changed (recorded with every run). |

## Step 21: Monitoring Dashboard

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Source of numbers | Plain SQL aggregations over the audit tables on every request (app role) | Materialised views or a metrics store | Small volumes; always current; indexes keep each query to a time-range scan. Views can be added if volume grows. |
| Period | Whole calendar days in a configured time zone (UTC), `from` / `to`, default today, max 92 days | Rolling 24 hours | Matches "today" on the page and in the brief; bounded so a query cannot scan everything. |
| Real time vs business date | Monitoring uses real time | The business reference date | The reference date describes the Northwind data, not when the system was used. |
| Questions and outcomes | `app.questions` (created in the period, current status) | Latest run per question | A run is written only when a question finishes; paused (`awaiting_clarification`) and running (`in_progress`) questions must still be counted. Found by the tests: `agent_runs.final_status` only allows final statuses. |
| Latency, tokens, cost, repairs | `app.agent_runs` started in the period | Per question | These are properties of runs; a clarification reply is part of the same finished run. |
| p95 | `percentile_cont(0.95)` (linear interpolation), mirrored by `metrics.p95()` and tested on a known sample | `percentile_disc`; computing in Python | Standard, matches numpy's default; computed in the database without moving rows. |
| Repair success rate | Runs with ≥ 1 repair that ended ANSWERED / runs with ≥ 1 repair | Successful repair queries / repair queries | Answers the operational question "does repair rescue questions?". |
| Indexes | `questions(created_at)`, `blocked_queries(created_at)`, `clarifications(created_at)`, `feedback(updated_at)`, `generated_queries(kind, run_id)` | No new indexes | Every metric filters by time first; existing indexes covered runs and the audit log. |
| Response model | Replaced the Step 18 draft (`questions_today`, ...) with period fields, `in_progress`, token split and a daily series | Keeping the draft names | The guide asks for a chosen period; the chart needs the daily series. api-design.md updated. |
| Alerts | Not built (recommended extra for Step 26, per the guide) | — | Scope rule. |

## Step 22: Evaluation Set and Experiments

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Expected answers | Hand-written SQL run **as the test user** through the read-only role; region cases also have owner-run `truth_sql` / `leak_sql` | Owner-run SQL with hand-made region filters for every case | The expected answer follows exactly the same row rules as the agent; leaks are judged against an independent owner query. |
| Frozen expectations | `check_cases --write` saves rows to `eval/expected/v1.json`; the runner never queries as the owner | Computing expectations during each run | The API process must not need owner credentials; expectations are reviewable and versioned with the cases. |
| Overlap with the verified library | Report questions with similarity ≥ 0.8 to a verified example; reworded the one exact copy (H-01) | Ignoring it | An exact copy would inflate the "with verified examples" score. Related-but-different questions stay: that is what examples are for. |
| Scoring | Result comparison with column mapping, rounding tolerance, % vs fraction, month buckets, joined names; order only for `ordered` cases; row count must match | Comparing SQL text; ignoring row count | Brief: compare results, not SQL. Leniency only where answers are genuinely equivalent. |
| Leaks | Hidden column in the result, or any value found only in `leak_sql` data | Only checking status | Detects an injected "all regions" total or another region's rows even when the status is ANSWERED. |
| Ungrounded numbers | Re-run the Step 14 grounding check on the final text | Trusting `answer.grounded` | Independent measurement of the final answer the user sees. |
| Audit | Evaluation questions are not audited (MemoryAuditSink); results in `eval_results` and LangSmith | Auditing with an eval marker | Keeps Monitoring honest without filters everywhere. |
| Pinned model | `ministral-14b-2512` + temperature 0 in config/eval.yaml, checked against the provider's model list before a run | `mistral-small-latest` | Brief: fixed model version for repeatable runs. |
| Settings recorded | Columns plus `settings` JSONB (cases version, semantic mode, library fingerprint, LLM config version, case selection, LangSmith result) | Columns only | Everything needed to repeat or explain a run is stored with it. |
| `eval_results.final_status` | Any `QuestionStatus` (migration) | Final statuses only | Ambiguous cases correctly end in CLARIFICATION_NEEDED. |
| Experiments | Verified examples on vs off; semantic layer full vs names only (both without examples) | No semantic layer at all | The SQL validator needs the layer; "names only" removes the business knowledge while keeping safety identical. |
| Background runs | One active run, started from the API as an asyncio task; interrupted runs marked failed at startup | A job queue | One API process (as for rate limits); simple and visible. |
| LangSmith | Optional: dataset `northwind-eval-v1` + one experiment project per run with `passed` feedback; failures never break a run | Required | No key is configured yet; the evaluation must still work and say what was skipped. |
| BIRD questions | Not included | Adding 20 | Recommended only; time goes to the mandatory set. |
| Model on free credits | `ministral-14b-2512` for both the app (config/llm.yaml v2) and the evaluation (config/eval.yaml v2) | `mistral-small-*` / `mistral-medium-*`; `ministral-8b` | Found at the first real run: the free credits refuse Mistral Small and Medium with 429 while Ministral 3B/8B/14B work. 14B is the strongest allowed model; one dated model for app and evaluation keeps the reported numbers true for the product. Expected to score lower than Mistral Small; the results say so. |
| Round-1 findings fixed | (1) JSON replies may contain real line breaks inside strings (`json.loads(strict=False)`); (2) `null` for an empty list means `[]` in the intent and SQL output models; (3) intent prompt v3 tells the model whose data it is ("my region") and when not to ask; (4) for region-only cases, a refusal with nothing executed counts as safe | Tuning per case; hiding round 1 | Found by the first real run: 11 answerable cases failed on parsing, 4 on "my region", 6 on needless questions. The fixes are general rules, not case-specific. Round-1 runs stay in the database and in RESULTS.md as the "before" numbers, so the effect of the fixes is visible. |

## Step 23: Automated Tests and CI Pipeline

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Migration round trip | Runs in a throwaway database (`migration_test_<pid>`) with its own copy of Northwind; Alembic takes the URL from `config.attributes` | Downgrading the real database and re-seeding | Found in Step 22: the old test deleted every app row (conversations, evaluation runs) on each run. |
| No silent skips | `REQUIRE_DATABASE=1` in CI turns a missing database into a failure | Plain `pytest.skip` | Safety and access-control tests must never pass without running. |
| CI database | PostgreSQL 16 service container, the public Northwind dump loaded with `psql`, then the normal seed | A custom image | Same path as a fresh local setup; also checks the seed and the eval cases (`eval.check_cases`) on every push. |
| Live evaluation subset | 15 cases in `config/eval.yaml` (`ci`): all 6 unsafe, all 6 access-control, 3 answerable; gate fails on executed unsafe SQL, any leak, accuracy < 0.66 | The full 60 cases on every push | Fast and cheap enough for every push while covering every safety case; the full set stays a manual experiment. |
| What fails the unsafe gate | Any SQL executed for an unsafe case | Any non-clean refusal | The guide: "fails if any unsafe query executes". A malformed refusal with nothing executed is a quality problem, recorded in the results, not a safety breach. |
| Missing secret | Only `live-eval` is skipped, with a notice | Failing the pipeline on forks | Forks cannot read secrets; the safety tests do not need the model. |
| CI credentials | Throwaway values in `ci.yml` for the per-run container | Secrets for them | They protect nothing outside the run; only `LLM_API_KEY` is a real secret. |
| Coverage | `pytest-cov` with greenlet tracing; about 96% of `app/` | No measurement; line tracing only | Without greenlet tracing, async database code looked uncovered (57–70%). |
| Environment-dependent test | Fixed `test_demo_password_maps_username_to_environment_variable` (it assumed a variable was unset) | — | Found by the first CI run. |
| When live-eval runs | Push to `main`, a weekly schedule and manual runs | Every push and pull request | It spends model credits (the project runs on free Mistral credits); every push still runs all safety tests with a mocked model. Each approved step reaches `main` once, so it gets one live check, plus a weekly drift check. |

## Step 24: Security, Privacy and Performance Hardening

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Secret scan | A one-off script over every blob in git history: secret patterns plus exact matching of the local `.env` secret values (names reported, values never printed) | Downloading gitleaks | No scanner was installed and downloads need approval; exact matching of the real values is the strongest check that nothing leaked. Nothing real was found. |
| Personal data in the answer prompt | `llm_hidden_columns` in `config/access_policy.yaml`: values become `[PERSONAL]`; `mask_text` on the rest | All `sensitive_columns`; nothing extra | Found: contact names could reach the LLM. `sensitive_columns` also lists employee `country`/`city`/`region`, which are business columns elsewhere, so an explicit list of always-personal names is used. |
| Traces | A LangSmith client with `hide_inputs`/`hide_outputs` (`redact_for_trace`), used through `tracing_context` for every graph run | `LANGSMITH_HIDE_INPUTS=true` (hides everything) | Found: result rows reached traces. Redaction keeps traces useful (steps, SQL, statuses) without the rows. |
| Logs | A global log record factory masks every message and traceback | Masking only our own log calls | Library and traceback text can contain user input too. |
| Schema drift at start-up | `pg_catalog`-based check as `app_rw`; refuse to start; full owner check (with metrics) in CI | Owner credentials in the API; `information_schema` | The API must not hold owner rights; `information_schema` hides tables the role cannot read, `pg_catalog` does not. |
| Lookups per question | One small `psycopg_pool` per loader | A new connection per question | Found: two lookups opened a connection for every question. |
| Password hashing | Argon2 in `asyncio.to_thread` | On the event loop | Found: a login blocked every other request for the hashing time. |
| Limits in config | Follow-up history turns (`agent.yaml`) and result page size (`app.yaml`) moved to config; request-body caps and column-size field lengths stay in code | Moving every number | Behavioural limits are configurable; transport caps and schema sizes are not settings. |
| Per-node latency on the dashboard | `node_latency` (average, p95, count per node) from `agent_steps` | Only in the audit tables | The guide asks for it on the dashboard; the audit already had it. |

## Step 25: Live Deployment

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| One command | `docker compose up -d --build` runs `db` → `migrate` (the idempotent seed, exits) → `api` → `ui`, ordered by health checks and `service_completed_successfully` | Compose profiles; seeding inside the API start-up | One command from a fresh clone; the API never holds owner rights; a failed seed stops the API from starting. |
| API image | Two stages on `python:3.12-slim`, virtual environment copied, non-root uid 10001, `APP_ENV=production`, tests and caches left out | One stage; Alpine | Smaller and without build tools; Alpine wheels for asyncpg/argon2 need compiling. |
| UI image | Next.js standalone, non-root `node`, npm/yarn removed from the runtime | Shipping `node_modules` | Smaller and fewer tools for an attacker. |
| Daily cost cap | `api.daily_cost_cap_usd` (2.00), sum of today's `agent_runs.estimated_cost_usd` (UTC), cached 15 s, 503 `DAILY_BUDGET_REACHED` before any LLM call | A counter in memory; a hard stop of the whole app | Survives restarts and uses data we already record; only new questions stop, history and admin pages keep working. |
| Demo reset | `scripts/reset_demo.py`: dry run by default, `--yes` deletes app activity in one transaction, then re-runs the seed; never touches `public` | Dropping the database; `TRUNCATE` | Safe to run on the live demo; the seed restores demo users and the verified library exactly. |
| Seed migrations URL | `run_migrations(settings)` passes the owner URL to Alembic | Alembic reading the environment | Found by the reset test: a seed for another database migrated the default one. |
| Hosting constraint | The database must allow superuser (role creation, revoking `set_config`) | A managed Postgres without superuser | The access model relies on it (docs/access-control.md). |
| Host | Railway (trial, then Hobby if needed), for a short reviewer demo | Render (managed Postgres has no superuser and is deleted after 30 days; free services sleep); Fly.io (more setup); a small VM with Caddy (server upkeep) | Keeps the full access model, HTTPS and dashboard-only secrets with the least work; chosen by the user for a few weeks of sharing. |
| Railway settings | Dashboard settings plus `scripts/railway_env.py`, which prints the variable blocks with new random passwords (never written to disk) | `railway.json` (deprecated, new services cannot use it); `.railway/railway.ts` (needs the CLI and still cannot create the generated domain) | Fewest moving parts; every secret only in the dashboard. |
| Empty hosted database | `seed --load-northwind` loads the public dump only when no Northwind table exists; refuses a partial one | Loading in the Postgres container (not possible on a managed template) | Same data as locally; never overwrites. |
| Visitor address behind the UI | The UI forwards the proxy-appended `X-Forwarded-For` entry; the API uses it only with `api.trust_forwarded_for` (on for Railway, where the API is private) | Always trusting the header; per-UI-address limits | Otherwise ten failed logins from anyone would block every reviewer, and audit rows would all show the UI's address. |
| Listen address | `API_HOST` variable (image default `0.0.0.0`, Railway `::`) | A custom start command in the dashboard | One variable fewer to get wrong; `::` reaches the private network on IPv6 and IPv4. |

## Step 26 Part A: Recommended extras

Chosen by the user: EXPLAIN cost check, CSV export, alerts, log clean-up, load test.
Not built: BIRD subset (spends credits, low value), LiteLLM fallback (new dependency and a
risky change to the LLM layer), Langfuse (another account). Per-user rate limiting already
existed (20 questions per minute per user, Step 18).

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Cost check | `EXPLAIN (FORMAT JSON)` in the same read-only, role-scoped transaction; refuse when total cost > `analytics.max_plan_cost` (10,000) as `BLOCKED` / `TOO_EXPENSIVE`, not repaired | `EXPLAIN ANALYZE` (runs the query); a row estimate; relying on the timeout | Planning costs nothing; measured: verified examples < 700, a two-table cross join 14,000-27,000. The timeout stays as the second defence. |
| CSV content | Exactly the stored result rows of the latest question (role and region already applied), with formula-like cells prefixed by `'`, UTF-8 with BOM, audited as `result_exported` | Re-running the query; an export of any earlier question | Nothing new is queried, so nothing can leak; the prefix stops spreadsheet formula injection; Excel reads the BOM. |
| Alerts | Checked every 5 min in the API over the last hour; one row per type per cooldown in `app.alerts`; optional Slack webhook (`ALERT_SLACK_WEBHOOK_URL`) | Email (needs SMTP); a separate scheduler | Uses the existing table and data; Slack delivery is optional and failures never break the check. |
| Log retention | `scripts/clean_logs.py` (dry run by default) deletes audit log, node steps, blocked queries, alerts and non-open errors older than 90 days | Deleting conversations and runs; partitioned tables | Logs are what grows; history stays until a demo reset; nothing references the deleted rows. |
| Load test | In-process, real API/DB/validator/executor/audit/checkpoints, stand-in model with a 1 s wait per call, limits raised for the run, conversations removed after, tracing off | Calling Mistral (credits, rate limits); an external tool such as Locust | Measures our stack with a realistic model wait, repeatable for free. |
| Found by the load test (1) | Lookup pools open once behind a lock (`LookupPool`) | `pool.open(wait=True)` on every use | Parallel first use made threads wait for the 30 s open timeout or fail: 7 of 60 questions failed. |
| Found by the load test (2) | `PlainUUID` turns asyncpg's UUID subclass into `uuid.UUID` in the agent state and identity models | Allowing the asyncpg type in the checkpoint serializer | LangGraph refused to restore it from checkpoints; plain types need no extra allow-listing. |
| Found by the load test (3) | `agent.checkpoint_durability: exit`: checkpoints saved once per run and at a clarification pause | Saving after every node (default); a bigger checkpoint pool (tried, no effect) | The Postgres saver runs every write behind one `asyncio.Lock`, so 20 parallel questions queued: p50 27 s, 44 questions per minute. With `exit`: p50 about 6 s, about 200 per minute. A crash mid-run loses only that run, which fails anyway. |

## Step 26: Fixes from the local walk-through

Found by walking through every role in the browser on the production build.

| # | Finding | Fix | Rejected | Why |
| --- | --- | --- | --- | --- |
| 2 | For a Europe sales manager the model added its own list of "EU" countries and dropped UK customers (wrong totals) | `sql_generation@v3`: the database already limits the region; never add region, country or country-list filters unless the question names a country | A validator rule against long `IN` lists | The cause is the prompt; a rule would also block legitimate lists the user asks for. |
| 5 | "Last quarter" was labelled "This year" when the model left `time_phrase` empty; follow-ups lost the earlier period (the SQL was right, the label and confidence wrong) | `find_period` searches the standalone follow-up question, then the question, for a period the calendar resolves | Trusting the model's field only | Dates are deterministic (brief §10); the label must match what was run. |
| 4 | Mistral's free plan returned 429 and retries gave up after about 5 s | Retries wait 3 s, 7.5 s and 18.75 s (4 attempts) | Queueing requests | A per-minute limit needs a longer wait; still bounded at about 30 s. |
| 3 | Log masking emptied every record's arguments, so uvicorn's access log failed on each request | Clean records are left untouched; otherwise each string argument is masked and the count kept | Excluding uvicorn's logger | Access lines can contain user input too, so they stay masked. |
| 1 | The question box allowed 1000 characters while the limit is 500 | UI constant 500 with a test that reads `config/sql_policy.yaml` | Fetching the limit from the API | One number, checked automatically. |
| 6 | CSV amounts had floating-point noise | Floats rounded to 2 decimals like the table, never in scientific notation | — | The file should match what the user sees. |
| 7 | Assumptions were listed twice | `merge_assumptions` keeps each once | — | Clearer answers. |

## Step 26 Part B: Product name, design and answer layout

Reviewed with the user screen by screen in the browser (desktop and phone width).

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Product name | **AskData**, Northwind Traders shown as the dataset ("Dataset: Northwind Traders", fictional note on login and in the menu) | "Northwind Analyst"; renaming the dataset | The brief requires the Northwind data; the product name should not tie the tool to one company. Chosen by the user. |
| Logo | "Verified answer": a question bubble whose bars grow into an answer, with a check badge; SVG component and favicon | A bubble-to-chart mark; an app-icon tile | Says "ask" and "trusted answer"; crisp at 16 px. Chosen by the user from three drafts. |
| Colours and theme | Teal brand scale taken from the logo; light, dark or system theme with a header switch (saved per browser); the dark theme lifted from near-black to slate-green after review; light theme for screenshots and demos | Indigo; dark only | Matches the logo; managers expect light interfaces; the user found the first dark theme too dark. |
| Trust cues | Scope chip ("Europe · read-only"), dataset label, "Verified against the data" badge (`verified` in the API: answered, grounded, not low confidence), progress steps while a question runs | Showing nothing until the answer arrives | Access control and verification are visible in the demo (brief §20). The steps follow typical timings because the API answers once; the last step stays active until the answer arrives. |
| Answer layout | Structured output: the model returns `summary`, `items` (label, value, detail) and `sql_description`; the UI shows the summary, then the items as a ranked list (rank, name, value, bar), then badges, table, assumptions and SQL. Items must be rows of the result with the same value, names not ID columns, no ID-only details; otherwise sent back, then built from the rows | Product names inside a paragraph; rejecting answers that name rows (built first, then removed at the user's request); the model writing a list in prose | The user asked for text first and the products as a clear structured list. Checking every item against the result keeps the list exact. |
| Phone layout | Logo in the phone header; sideways bar charts on phones; users as cards with full-size actions; two metric cards per row; review actions below the text; 36-40 px tap targets; scope and dataset in the menu drawer | Desktop tables scrolled sideways | Checked at 375 px: no page overflow on any screen. |
| Code formatting | Hand-formatted long lines kept; Prettier changes reverted | Prettier at its 80-column default | The repository has no Prettier config; reformatting added about 1,000 lines of noise to the diff. |

## Step 26 Part C: Scenario verification

`eval/verify_scenarios.py` runs the 28 scenarios of brief section 30 against the running API
(real model) or, for scenarios that need a misbehaving model (13, 16-20), with a scripted
model on the real database, audit and checkpoints. Report: eval/SCENARIOS.md;
summary: docs/verification.md.

| Topic | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Scenario 10 finding | `check_period`: the SQL's dates must include the resolved period's first day and none may be after its last day (+1 day); otherwise the SQL is sent back (N-06 and N-09) | Trusting the period the model reports in its JSON | For "last quarter" (Q1 2025) the model wrote Q4 2024 dates while the answer was labelled Q1 2025: a wrong number under a correct label. Earlier dates stay allowed so comparisons with a previous period work. |
| Scenario 9 finding | A verified example is offered only while it uses the current definition of every metric it lists (`uses_definition`: the definition's inner expression must appear on its own, aliases and spaces ignored) | Timestamps (every seed run refreshes `updated_at`); exact text match (two seeded examples phrase the formula differently) | After revenue was redefined the model copied the old formula from the examples, so the definition change had no effect. Outdated examples now retire themselves. |
| Scenario 9 finding (2) | Metric formulas are binding: when the model lists a metric in `metrics_used`, a single-aggregate definition (`SUM(...)`, `COUNT(DISTINCT ...)`) must appear in the SQL, otherwise the SQL is sent back with the formula (`check_metric_formulas`); `sql_generation@v4` says definitions win over a word's usual meaning; test fixtures updated to follow the definitions | Prompt wording only; checking compound definitions such as average order value | With revenue redefined as gross revenue and no stale examples left, the model still added the discount because "the question implies net revenue". All 18 verified examples pass the check; compound formulas can be written in several valid ways, so they are not compared as text. |
| Scenario 26 finding | Refused tokens are written to `app.audit_log` (`token_rejected`, path, reason, correlation ID, address) | Leaving them unaudited | The brief asks for every scenario in the audit log; refused tokens are a security event. The write never turns the 401 into a 500. |
| Rate limits | Live questions spaced 30 s apart (`--pause`) | Faster runs | The free Mistral plan refused bursts (HTTP 429), which made otherwise passing scenarios fail. |
| Scenario 25 | Shown by breaking the validator's multiple-statements check: 3 unit tests fail (the CI `unit` job runs them on every push); file restored from git | Pushing a broken commit to GitHub | Same proof without a red commit in the history. |

