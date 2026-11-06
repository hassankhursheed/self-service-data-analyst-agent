# CLAUDE.md

Self-Service Data Analyst Agent: a governed text-to-SQL assistant for the fictional
Northwind Traders company. It is built in 26 small steps; progress is tracked in
`docs/progress.md` and decisions in `docs/decisions-log.md`.

## Standing rules

1. **Source of truth.** `docs/capstone-brief.pdf` is the source of truth. If anything is
   unclear or conflicts, ask the user instead of guessing.
2. **Scope.** Work only on the current step. Do not build features from later steps.
3. **Code style.** Python 3.12, type hints everywhere, Pydantic models for data passed
   between parts, small modules with one responsibility each.
4. **Data safety.** The application never writes to Northwind tables. The agent uses a
   read-only role.
5. **Secrets.** No secrets in code, tests, docs or screenshots. Settings come from
   environment variables. Only `.env.example` is committed, with placeholder values.
6. **Data.** Only fictional data. No real company, customer or patient data anywhere.
7. **Tests.** Every new piece of logic gets pytest tests. LLM calls are mocked in unit
   tests.
8. **Config.** Prompts, model names, limits and the business reference date live in
   versioned config files, never hard-coded in Python.
9. **End-of-step routine.** Run all tests and linters. Update `docs/progress.md` (tick the
   step, list what is left) and `docs/decisions-log.md` (what you chose, what you rejected
   and why). Then give the user a short summary of changed files and exact commands to
   verify the step. Stop and wait. Commit only after the user says "approved, commit",
   with a short, relevant message of about 4 to 7 words that describes the change
   (no "Step N" prefix), for example `Add sqlglot-based SQL safety validator`.

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
docs/        brief, progress, decisions log, diagrams
data/northwind/  public Northwind PostgreSQL dump (read-only source data)
```

## Commands

```bash
python -m venv .venv            # Python 3.12
.venv/Scripts/activate          # Windows; use .venv/bin/activate elsewhere
pip install -e ".[dev]"
cp .env.example .env            # then replace the placeholders
docker compose up -d            # PostgreSQL 16 with Northwind (host port 5433)
python scripts/db_check.py      # row counts of every Northwind table
python -m scripts.seed          # migrations, date shift, regions, users, roles, views, semantic layer
alembic upgrade head            # migrations only (the seed also runs them)
python scripts/generate_erd.py  # after changing models
pytest                          # integration tests skip if the database is down
ruff check .
ruff format --check .
mypy
```
