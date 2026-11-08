# Deployment

Brief §29. How to start the whole system with one command, what it needs, how to put it
online over HTTPS, how to reset the demo and how to roll back.

## One command (local or any Docker host)

```bash
git clone https://github.com/hassankhursheed/self-service-data-analyst-agent.git
cd self-service-data-analyst-agent
cp .env.example .env          # then replace every CHANGE_ME (see the variable list below)
docker compose up -d --build
```

Compose starts, in order (`docker-compose.yml`):

| Service | What it does | Starts when |
| --- | --- | --- |
| `db` | PostgreSQL 16; loads the public Northwind dump on first start (empty volume) | immediately |
| `migrate` | runs the idempotent seed: migrations, the one-time date shift, roles and grants, secure views, demo users, semantic layer, verified examples; then exits | `db` is healthy |
| `api` | FastAPI on port 8000; refuses to start if the semantic layer does not match the database | `migrate` finished successfully |
| `ui` | Next.js on port 3000 | `api` is healthy |

Open http://localhost:3000 and sign in with a demo account. Checked from a fresh copy of
the repository (Step 25): all four services came up and a demo login worked.

`docker compose up -d db` starts only the database (tests, or the API run on the host).

## Images

| Image | Base | Notes |
| --- | --- | --- |
| `data-analyst-agent-api` | `python:3.12-slim`, two stages | dependencies in a virtual environment built in a separate stage (pinned by `docker/constraints.txt`); runs as the non-root user `api` (uid 10001); `APP_ENV=production` by default; health check on `/health`; also used by `migrate` |
| `data-analyst-agent-ui` | `node:24-alpine`, three stages | Next.js standalone output only; npm and yarn removed from the runtime; runs as the non-root user `node`; health check on `/login` |

No secret is baked into an image: `.env` is excluded by `.dockerignore`; settings come from
the environment at run time.

## Environment variables

Set these in `.env` locally, or in the host's dashboard (never in files) when deployed.

| Variable | Required | Meaning |
| --- | --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | yes | database owner (seed and migrations only; the app never uses it) |
| `POSTGRES_HOST`, `POSTGRES_PORT` | yes | where the owner connects (inside Compose `db:5432` is set automatically) |
| `APP_DATABASE_URL` | yes | `postgresql+asyncpg://app_rw:<password>@<host>:<port>/<db>`: the application role; the seed creates the role with this password |
| `ANALYTICS_DATABASE_URL` | yes | `postgresql+asyncpg://analytics_ro:<password>@<host>:<port>/<db>`: the read-only agent role |
| `JWT_SECRET_KEY` | yes | token signing key; at least 32 characters when `APP_ENV=production` |
| `LLM_API_KEY` | yes | Mistral API key (model in `config/llm.yaml`) |
| `APP_ENV` | no | `development` (default), `test` or `production` |
| `DEMO_PASSWORD_<USER>` | for demo accounts | password of each demo user (`config/test_users.yaml`), e.g. `DEMO_PASSWORD_SALES_EUROPE` |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` | no | tracing (traces are redacted, docs/security.md) |
| `API_BASE_URL` | UI only | where the UI server reaches the API (`http://api:8000` in Compose) |
| `UI_INSECURE_COOKIES` | UI only | `1` only for plain HTTP on localhost; leave unset behind HTTPS so cookies are `Secure` |
| `API_PORT`, `UI_PORT` | no | host ports in Compose (default 8000, 3000) |
| `ALERT_SLACK_WEBHOOK_URL` | no | Slack incoming webhook for alerts (docs/monitoring.md); without it alerts are stored and logged |

Non-secret settings (CORS origins, rate limits, cost cap, page sizes, prompts, model) live
in the versioned `config/` files; override nested values with `__`, for example
`API__DAILY_COST_CAP_USD=1.0` or `API__CORS_ORIGINS='["https://demo.example.com"]'`.

## Demo accounts

The seed creates the test users of `config/test_users.yaml` with the passwords from
`DEMO_PASSWORD_*`:

| Username | Role | Region | Shows |
| --- | --- | --- | --- |
| `sales.europe` | Sales manager | Europe | region-only data |
| `sales.americas` | Sales manager | Americas | region-only data |
| `sales.other` | Sales manager | Rest of world | region-only data |
| `finance` | Finance analyst | all | revenue, discounts, freight |
| `operations` | Operations manager | all | stock, suppliers, shipping; no customer contact details |
| `admin` | Admin | — | admin pages only, no business data |
| `no.role` | none | — | is refused |
| `disabled.user` | Finance analyst (disabled) | — | cannot sign in |

For a public demo use new, strong demo passwords set only in the host's dashboard.

## Abuse protection

| Protection | Setting | Default |
| --- | --- | --- |
| Question length | `config/sql_policy.yaml` `max_question_length` | 500 characters |
| Questions per user | `config/app.yaml` `api.rate_limits.questions_per_minute` | 20 per minute |
| Logins per address | `api.rate_limits.logins_per_minute_per_ip` | 10 per minute |
| Daily cost cap | `api.daily_cost_cap_usd` | $2.00 per UTC day; then new questions get a friendly "try again tomorrow" (503) while the rest of the app works |
| Expensive queries | `config/app.yaml` `analytics.max_plan_cost` | refused before running when the planner estimate is above 10,000 |
| Per-question budget | `config/llm.yaml` `budget` | 20,000 tokens / $0.05 |
| Query limits | `config/app.yaml` `analytics` | 10 s statement timeout, 1,000 rows |

Rate limits are kept in memory, so run one API process (docs/security.md).

## Reset the demo

```bash
python -m scripts.reset_demo            # dry run: shows what would be removed
python -m scripts.reset_demo --yes      # reset (add --keep-eval to keep evaluation runs)
```

Inside Compose: `docker compose run --rm migrate python -m scripts.reset_demo --yes`.
It removes conversations, questions, runs, feedback, errors, the audit log, alerts,
checkpoints, non-demo users and evaluation runs in one transaction, then re-runs the seed
(demo passwords, roles, regions, the verified library). The Northwind data is never
touched.

## Roll back

- **Application:** images are built from git; to roll back, check out the previous
  release tag or commit and run `docker compose up -d --build api ui` (on a host: redeploy
  the previous build from its dashboard).
- **Database schema:** migrations are additive; to undo the last one run
  `docker compose run --rm migrate alembic downgrade -1` before deploying the older code.
  Downgrades keep data where they can (Step 22 made them safe with real data).
- **Demo data:** `python -m scripts.reset_demo --yes`.
- **Configuration:** settings are versioned in `config/`; roll back with the code.

## Hosting requirement

The database role setup needs a PostgreSQL where the owner is a **superuser** (or at least
can create roles and revoke `pg_catalog.set_config`): the seed revokes `set_config` from
everyone so a query can never change its own role or region (docs/access-control.md).
Managed databases that do not grant this cannot run the access model safely, so the
database must run as a container or on a server we control.

## Live deployment: Railway

Chosen in Step 25 (docs/decisions-log.md): Railway runs our Dockerfiles from GitHub,
its PostgreSQL is a container where the owner `postgres` is a superuser, and every
service gets HTTPS. Meant for a short demo for reviewers (the trial credit; Hobby after
that). Check current pricing on railway.com.

Railway's `railway.json` config files are deprecated and new services cannot use them,
so the few settings are made in the dashboard. Every secret is set only there.

```text
Internet ──HTTPS──▶ ui (public domain, port 3000)
                     │ private network
                     ▼
                    api (no public domain, port 8000) ──▶ Postgres (volume)
```

### 1. Prepare the variables (on your computer)

```bash
python -m scripts.railway_env
```

This prints two blocks with new random passwords. It is the only copy: keep the
`DEMO_PASSWORD_*` lines in a password manager to share with reviewers. Do not commit or
screenshot them.

### 2. Create the project

1. railway.com → **New Project** → **Deploy PostgreSQL**. Keep the name `Postgres`
   (the variables refer to it).
2. **Create** → **GitHub Repo** → `self-service-data-analyst-agent`. Rename the service to
   `api` (Settings → name).
   - **Settings → Deploy → Pre-deploy command:** `python -m scripts.seed --load-northwind`
   - **Settings → Deploy → Healthcheck path:** `/health`
   - Do **not** generate a public domain for `api`.
   - **Variables → Raw Editor:** paste the `api` block, then replace `LLM_API_KEY` with your
     Mistral key. Deploy.
3. **Create** → **GitHub Repo** → the same repository again. Rename it to `ui`.
   - **Settings → Source → Root directory:** `/ui`
   - **Settings → Deploy → Healthcheck path:** `/login`
   - **Variables → Raw Editor:** paste the `ui` block. Deploy.
   - **Settings → Networking → Generate Domain**, port `3000`. This is the live URL.

The first `api` deploy loads Northwind into the empty database and runs the seed (roles,
date shift, views, demo users, semantic layer, verified examples). Later deploys run the
same idempotent seed and change nothing that is already there.

### 3. Check

Open `https://<ui domain>/login` and sign in as `sales.europe`, `finance`, `operations` and
`admin` with the demo passwords; `no.role` is refused and `disabled.user` cannot sign in
(scenario 28). The `api` deploy log shows `Seed complete`; its HTTP log shows `/health`.

### Railway-specific settings

| Variable | Why |
| --- | --- |
| `RAILWAY_DOCKERFILE_PATH=docker/api.Dockerfile` | the API Dockerfile is not at the repository root |
| `API_HOST=::` | Railway's private network uses IPv6 (and IPv4 in new environments) |
| `API__TRUST_FORWARDED_FOR=true` | the API is only reachable from the UI, so it may use the visitor address the UI forwards for login limits and the audit log |
| `${{Postgres.*}}` references | Railway fills in the database host, user and password |

### Daily log clean-up on Railway (optional)

Add one more service from the same repository, named `clean-logs`, with
`RAILWAY_DOCKERFILE_PATH=docker/api.Dockerfile`, the same database variables as `api`
(copy them in the Raw Editor), **Settings → Deploy → Custom start command**
`python -m scripts.clean_logs --yes` and **Cron schedule** `0 3 * * *`. It runs once a
day and exits. For a demo of a few weeks this is not needed.

### Reset and roll back on Railway

- **Reset the demo:** install the Railway CLI, run `railway link`, then
  `railway ssh --service api` and inside it `python -m scripts.reset_demo --yes`.
- **Roll back:** `api` or `ui` → **Deployments** → an earlier deployment → **Rollback**.
  For a schema change, run `alembic downgrade -1` through `railway ssh` first.
- **Stop spending:** remove the services (or the project) in the dashboard when the
  review is over.
