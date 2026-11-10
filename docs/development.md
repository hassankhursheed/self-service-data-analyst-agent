# Development

Working on AskData without Docker, and the commands used day to day.

## How settings fit together

- Secrets and environment-specific values come from environment variables (a local
  `.env` file, copied from `.env.example`, is gitignored).
- Non-secret settings live in `config/app.yaml` (versioned).
- `app/core/config.py` loads both. Priority: environment variables > `.env` >
  `config/app.yaml` > defaults. Nested YAML values can be overridden with `__`,
  e.g. `APP__LOG_LEVEL=DEBUG`.

## Layout

```
app/
  api/       FastAPI routes, request and response models
  agent/     LangGraph graph, state and nodes
  db/        engines, sessions, application-data models
  semantic/  semantic layer and business calendar
  safety/    SQL parsing, validation and policy
  core/      settings and shared building blocks
ui/          Next.js + React + TypeScript + Tailwind CSS user interface
migrations/  Alembic migrations
scripts/     seed and maintenance scripts
config/      versioned non-secret configuration
eval/        evaluation datasets and scripts
tests/unit/, tests/integration/
docs/        design notes, decisions log, diagrams
data/northwind/  public Northwind PostgreSQL dump (read-only source data)
```

## Commands

```bash
python -m venv .venv            # Python 3.12
.venv/Scripts/activate          # Windows; use .venv/bin/activate elsewhere
pip install -e ".[dev]"
cp .env.example .env            # then replace the placeholders
docker compose up -d db         # PostgreSQL 16 with Northwind only (host port 5433)
python scripts/db_check.py      # row counts of every Northwind table
python -m scripts.seed          # migrations, date shift, regions, users, roles, views, semantic layer
alembic upgrade head            # migrations only (the seed also runs them)
python scripts/generate_erd.py  # after changing models
python scripts/run_api.py       # API on http://127.0.0.1:8000 (docs at /docs)
npm --prefix ui install         # once; then: npm --prefix ui run dev (http://localhost:3000)
npm --prefix ui run lint && npm --prefix ui run typecheck && npm --prefix ui test
docker compose up -d --build    # whole stack: db, migrate + seed, api, ui
python -m scripts.reset_demo    # dry run; --yes resets demo data (never Northwind)
python -m eval.check_cases --write             # after changing eval/cases.yaml
python -m eval.run_eval --experiment NAME      # evaluation run (needs LLM_API_KEY)
pytest                          # integration tests skip if the database is down
ruff check .
ruff format --check .
mypy
```

## Conventions

- Python 3.12, type hints everywhere, Pydantic models for data passed between parts,
  small modules with one responsibility each.
- The application never writes to Northwind tables; the agent uses a read-only role.
- No secrets in code, tests, docs or screenshots; only `.env.example` is committed.
- Prompts, model names, limits and the business reference date live in versioned config
  files, never in Python.
- Every new piece of logic gets pytest tests; LLM calls are mocked in unit tests.
