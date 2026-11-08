# Continuous integration

Brief §25. `.github/workflows/ci.yml` runs on every push and pull request, so a regression
is caught before it reaches users.

| Job | What it runs | Fails when |
| --- | --- | --- |
| `lint` | `ruff check`, `ruff format --check`, `mypy` (strict) | any lint, format or type error |
| `unit` | `pytest tests/unit` with coverage; every LLM call is mocked (scripted model) | any test fails |
| `integration` | PostgreSQL 16 service container → load the public Northwind dump → `python -m scripts.seed` → `python -m eval.check_cases` → `pytest tests/integration` with coverage | any test fails, the database is missing, or an evaluation case no longer matches the data |
| `ui` | `npm ci`, eslint, `tsc --noEmit`, Vitest, `next build` | any check fails |
| `live-eval` | the `ci.cases` subset of `config/eval.yaml` (15 cases: every unsafe and access-control case plus three answerable ones) with the real, pinned model: `python -m eval.ci_gate` | any unsafe case executes SQL, any case leaks data, or answerable accuracy is below `ci.min_accuracy` (0.66) |

## Safety tests are never skipped

Locally, integration tests skip when PostgreSQL is not running. In CI the variable
`REQUIRE_DATABASE=1` turns that skip into a failure, so the SQL-safety, row-level access
and access-control tests can never pass silently without running.

Only `live-eval` may be skipped: when the `LLM_API_KEY` secret is not available (for
example on a pull request from a fork), its first step writes a notice ("Live evaluation
skipped ... the safety tests in 'unit' and 'integration' still ran") and the other steps
do not run. The other jobs never use the secret.

## Secrets and test values

- `LLM_API_KEY` is a GitHub Actions repository secret (Settings → Secrets and variables →
  Actions). It is read only by `live-eval`.
- The database passwords, the JWT key and the demo passwords in `ci.yml` are throwaway
  values for the temporary service container of each run; they protect nothing.
- LangSmith is not used in CI (`LANGSMITH_TRACING=false`).

## What the tests cover

`pytest --cov` (coverage measured with greenlet tracing, `pyproject.toml`): about 96% of
`app/` overall. The areas named in the brief:

| Area | Where | Coverage of the module |
| --- | --- | --- |
| SQL validator | `tests/unit/test_sql_validator.py`, `tests/integration/test_validator_db.py` | 96% |
| Allow-lists (functions, tables, columns, access policy) | `test_sql_validator.py`, `test_access_setup.py` | 92–96% |
| Date resolution | `test_calendar.py`, `test_calendar_db.py` | 99% |
| Chart selection | `test_answers.py` | 97% |
| Structured-output parsing | `test_llm.py`, `test_intent.py`, `test_sql_path.py` | 94–97% |
| Login and tokens | `test_tokens.py`, `test_auth_db.py`, `test_api.py` | 94–98% |
| Row-level security per test user | `test_access_control.py`, `test_production_wiring_db.py` | — (database) |
| API endpoints | `test_api.py`, `test_verified_db.py`, `test_metrics_db.py`, `test_eval_db.py` | 96–98% |
| Main graph paths | `test_agent_graph.py`, `test_sql_path*.py`, `test_follow_ups.py`, `test_conversations_db.py` | 96–98% |

The migration round trip (`test_migrations.py`) runs in a throwaway database with its own
copy of Northwind, so running the suite never deletes application data.

## Run the same checks locally

```bash
ruff check . && ruff format --check . && mypy
pytest tests/unit
REQUIRE_DATABASE=1 pytest tests/integration     # needs docker compose up -d and the seed
python -m eval.ci_gate                           # needs LLM_API_KEY
npm --prefix ui run lint && npm --prefix ui run typecheck && npm --prefix ui test
```
