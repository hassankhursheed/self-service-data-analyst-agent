# HTTP API

The FastAPI service in `app/api/` (brief §19, §22). The contract (every endpoint, model
and error) is in [design/api-design.md](design/api-design.md); interactive OpenAPI docs
are served at `/docs` while the API runs.

## Run it

```bash
docker compose up -d db         # PostgreSQL with Northwind
python -m scripts.seed          # once: migrations, users, roles, views, semantic layer
python scripts/run_api.py       # http://127.0.0.1:8000, docs at /docs
```

`scripts/run_api.py` uses the selector event loop on Windows (psycopg's async pool needs
it). The API needs `JWT_SECRET_KEY`, the database URLs and `LLM_API_KEY` in `.env`.

## Layout

| Module | Responsibility |
| --- | --- |
| `app/api/main.py` | `create_app()`: lifespan (engine, checkpointer, agent, services), middleware, routers |
| `app/api/middleware.py` | Correlation ID per request; turns unexpected errors into a generic 500 |
| `app/api/errors.py` | Error body `{correlation_id, error: {code, message}}` and code -> HTTP status |
| `app/api/ratelimit.py` | In-memory sliding-window limiter |
| `app/api/deps.py` | Service container, correlation ID, paging dependencies |
| `app/api/schemas.py` | Request and response models (including the ones for later steps) |
| `app/api/routes/` | `public` (login, health), `questions` (ask, clarify, conversations, feedback), `admin` |
| `app/services/feedback.py`, `app/services/review.py` | Feedback, blocked and error lists, re-run |

## Behaviour worth knowing

- **Correlation ID:** send a UUID in `X-Correlation-ID` to choose it; anything else is
  replaced. It is returned in the header and in every body, and it is the agent run's ID,
  so it finds the audit rows (`app.agent_runs.correlation_id`) and the LangSmith trace.
- **Agent outcomes are 200:** `BLOCKED`, `FAILED` and `CLARIFICATION_NEEDED` come back as
  normal responses with a `status`. Users without a business role and admins get 403
  (`NO_ROLE`, `ADMIN_ONLY`) *after* the agent has audited the rejection.
- **Errors never include internals:** unexpected errors return
  `INTERNAL_ERROR` with a generic message; the details go to the server log with the
  correlation ID.
- **Ownership:** another user's conversation or question answers 404, so its existence is
  not revealed.
- **Re-run:** `POST /admin/errors/{id}/rerun` runs the logged (masked) question again as
  the original user, with that user's *current* role and region; each error can be re-run
  once (409 afterwards).
- **501 endpoints:** metrics, verified queries and evaluation routes exist with their final
  models and return `NOT_IMPLEMENTED` until their step.

- **CSV download:** `GET /conversations/{id}/table.csv` returns every result row of the
  latest question as CSV (what the table shows, already limited to the user's role and
  region). Owner only (404 otherwise); each download is an audit event `result_exported`.
- **Alerts:** `GET /admin/alerts?limit=` lists the newest alerts (admin only).

## Settings (`config/app.yaml`, section `api`)

| Setting | Default | Meaning |
| --- | --- | --- |
| `cors_origins` | `["http://localhost:3000"]` | Browser origins allowed to call the API (the UI) |
| `rate_limits.questions_per_minute` | 20 | Per user, for `/ask` and `/clarify` |
| `rate_limits.logins_per_minute_per_ip` | 10 | Per client IP, for `/auth/login` |
| `default_page_size` / `max_page_size` | 20 / 100 | Paging of list endpoints |

## Limitations

- Rate limits live in the memory of one API process. They reset on restart and are not
  shared between workers; a shared store (for example Redis) is needed to scale out.
- A request runs the agent inline; a slow LLM call keeps the HTTP request open (the agent's
  own timeouts and budgets still apply).
