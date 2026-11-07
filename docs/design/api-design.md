# API design

Brief sections 8, 16, 19 and 22. A FastAPI service with OpenAPI docs at `/docs`. All
endpoints are async; request and response bodies are Pydantic models.

## Shared conventions

- **Authentication:** `Authorization: Bearer <JWT>` on every endpoint except
  `POST /auth/login` and `GET /health`. The token carries `sub` (user id), `role`,
  `region`, `token_version` and `exp`. The server re-checks `is_active` and
  `token_version` on every call, so disabling a user stops existing tokens at once.
- **Correlation ID:** the client may send `X-Correlation-ID`; otherwise the server creates
  one. It is returned in the `X-Correlation-ID` header **and** as `correlation_id` in every
  response body, including errors.
- **Pagination:** list endpoints accept `page` (default 1) and `page_size` (default 20,
  max 100) and return `total`.
- **Agent outcomes are not HTTP errors:** `BLOCKED`, `FAILED` and `CLARIFICATION_NEEDED`
  come back as `200` with a `status` field and a plain-language message. HTTP errors are for
  request problems (below).

### Error model

```json
{
  "correlation_id": "6f1c2b9e-1d2a-4a5b-9c1e-3f4d5e6a7b8c",
  "error": {"code": "TOKEN_EXPIRED", "message": "Your session has expired. Please log in again."}
}
```

| HTTP | When | Example codes |
| --- | --- | --- |
| 400 | Invalid body, empty or too-long question | `VALIDATION_ERROR`, `QUESTION_TOO_LONG` |
| 401 | Missing, invalid or expired token; wrong password; disabled user | `INVALID_TOKEN`, `TOKEN_EXPIRED`, `INVALID_CREDENTIALS` |
| 403 | Logged in but not allowed (no role, not admin, someone else's conversation) | `NO_ROLE`, `ADMIN_ONLY`, `FORBIDDEN` |
| 404 | Resource not found (or not owned by the caller) | `NOT_FOUND` |
| 409 | Conflict (already re-run, no pending clarification, username taken) | `CONFLICT`, `NO_PENDING_CLARIFICATION`, `USERNAME_TAKEN` |
| 429 | Rate limit exceeded | `RATE_LIMITED` |
| 501 | Endpoint built in a later step | `NOT_IMPLEMENTED` |
| 500 | Unexpected server error (no stack trace is returned) | `INTERNAL_ERROR` |

Login failures return the same `INVALID_CREDENTIALS` for an unknown user, a wrong
password and a disabled account, so the API does not reveal which usernames exist.

## Shared models

`AskResponse` is returned by `/ask`, `/clarify` and inside conversation details:

```json
{
  "correlation_id": "6f1c2b9e-1d2a-4a5b-9c1e-3f4d5e6a7b8c",
  "conversation_id": "0b7d4c1a-6a8e-4c43-9f0f-2a1e5b8c9d10",
  "question_id": "c3a0e9b2-7d64-4f1b-8e2a-5d9c0b1a2e3f",
  "status": "ANSWERED",
  "message": "Revenue in Europe last quarter was 81,234.50.",
  "answer": {"text": "...", "confidence": "high", "low_confidence": false},
  "sql": {"text": "SELECT ...", "description": "Sums order revenue for European customers in Q1 2025."},
  "date_range": {"from": "2025-01-01", "to": "2025-03-31", "label": "Last quarter = 1 Jan to 31 Mar 2025"},
  "assumptions": ["Revenue includes discounts."],
  "chart": {"type": "metric_card", "spec": {}},
  "table": {"columns": ["revenue"], "rows": [[81234.5]], "row_count": 1, "page": 1, "page_size": 50, "truncated": false},
  "clarification": null,
  "block": null,
  "trace_url": "https://smith.langchain.com/..."
}
```

- `status`: `ANSWERED`, `CLARIFICATION_NEEDED`, `BLOCKED`, `REJECTED` or `FAILED`.
- `chart`: `{type: line | bar | metric_card | none, x, y, data, title, reason}`, a neutral
  spec the Next.js UI draws (see `docs/answers-and-charts.md`).
- `clarification` (when `CLARIFICATION_NEEDED`): `{"clarification_id": 12, "question": "...", "options": ["...", "..."]}`.
- `block` (when `BLOCKED`): `{"reason_code": "WRITE_STATEMENT", "message": "..."}`.

## Endpoints

### `POST /auth/login`
- **Access:** public.
- **Request:** `LoginRequest {username: str, password: str}`
- **Response:** `200 LoginResponse {correlation_id, access_token, token_type: "bearer", expires_in, user: {username, display_name, role, region}}`
- **Errors:** 400, 401, 429, 500. Every success and failure is written to the audit log.

```json
{"username": "sales.europe", "password": "<demo password>"}
```

### `GET /health`
- **Access:** public.
- **Request:** none.
- **Response:** `200 HealthResponse {correlation_id, status: "ok" | "degraded", database: "ok" | "down", version}`; `503` with the same body when the database is down.
- **Errors:** 500.

```json
{"correlation_id": "...", "status": "ok", "database": "ok", "version": "0.1.0"}
```

### `POST /ask`
- **Access:** logged-in user with a business role (sales, finance, operations). No role: 403 `NO_ROLE`; admin: 403 `ADMIN_ONLY` (business questions are off by default for admins).
- **Request:** `AskRequest {question: str (1-1000 chars), conversation_id: UUID | null}`. A null `conversation_id` starts a new conversation; otherwise it is a follow-up and the conversation must belong to the caller.
- **Response:** `200 AskResponse`.
- **Errors:** 400, 401, 403, 404, 429, 500.

```json
{"question": "Which five products lost the most revenue last quarter compared with the quarter before?", "conversation_id": null}
```

### `POST /clarify`
- **Access:** logged-in user; only the owner of the question.
- **Request:** `ClarifyRequest {conversation_id: UUID, answer: str}` (one of the offered options or free text, same length limits). A conversation has at most one paused question, so the conversation identifies it.
- **Response:** `200 AskResponse` (the run resumes from `CLARIFICATION_NEEDED`). The correlation ID is the paused question's, so it matches its audit rows and trace.
- **Errors:** 400, 401, 404 (not the caller's conversation), 409 `NO_PENDING_CLARIFICATION`, 429, 500.

```json
{"conversation_id": "0b7d4c1a-...", "answer": "By revenue, for 2024"}
```

Design change (Step 18): the draft used `{question_id, clarification_id, answer}`.

### `GET /conversations`
- **Access:** logged-in user; own conversations only.
- **Request:** query `page`, `page_size`.
- **Response:** `200 ConversationList {correlation_id, items: [{id, title, created_at, updated_at, question_count}], total, page, page_size}`
- **Errors:** 401, 500.

```json
{"correlation_id": "...", "items": [{"id": "0b7d...", "title": "Revenue last quarter", "created_at": "...", "updated_at": "...", "question_count": 3}], "total": 1, "page": 1, "page_size": 20}
```

### `GET /conversations/{id}`
- **Access:** logged-in user; own conversation only (others return 404).
- **Request:** path `id`.
- **Response:** `200 ConversationDetail {correlation_id, id, title, questions: [{id, correlation_id, question, status, created_at}], latest: AskResponse | null}` (the checkpointer keeps the full state of the latest question only).
- **Errors:** 401, 404, 500.

```json
{"correlation_id": "...", "id": "0b7d...", "title": "Revenue last quarter", "questions": [{"question_id": "c3a0...", "status": "ANSWERED", "message": "..."}]}
```

### `POST /feedback`
- **Access:** logged-in user; only for their own questions.
- **Request:** `FeedbackRequest {question_id: UUID, rating: "helpful" | "not_helpful", comment: str | null (max 1000)}`. Sending again updates the rating.
- **Response:** `200 FeedbackResponse {correlation_id, feedback_id, rating}`
- **Errors:** 400, 401, 403, 404, 500.

```json
{"question_id": "c3a0...", "rating": "not_helpful", "comment": "Missing the discount."}
```

### `GET /admin/metrics`
- **Access:** admin.
- **Request:** query `date` (default: today).
- **Response:** `200 MetricsResponse {correlation_id, questions_today, questions_by_role, outcomes: {answered, blocked, rejected, failed}, blocked_by_reason, repair_attempts, repair_success_rate, clarifications_asked, latency_avg_ms, latency_p95_ms, tokens_today, cost_today_usd, feedback: {helpful, not_helpful}, latest_eval_run, failed_logins}`
- **Errors:** 401, 403, 500.

```json
{"correlation_id": "...", "questions_today": 42, "questions_by_role": {"sales_manager": 30, "finance_analyst": 12}, "outcomes": {"answered": 35, "blocked": 4, "rejected": 1, "failed": 2}, "blocked_by_reason": {"WRITE_STATEMENT": 3, "HIDDEN_COLUMN": 1}, "repair_attempts": 5, "repair_success_rate": 0.8, "clarifications_asked": 6, "latency_avg_ms": 3100, "latency_p95_ms": 7200, "tokens_today": 98000, "cost_today_usd": 0.41, "feedback": {"helpful": 20, "not_helpful": 3}, "latest_eval_run": null, "failed_logins": 2}
```

### `GET /admin/blocked`
- **Access:** admin.
- **Request:** query `page`, `page_size`, `reason_code`, `from`, `to`.
- **Response:** `200 BlockedList {correlation_id, items: [{id, correlation_id, username, role, question, stage, reason_code, reason_text, sql_text, created_at}], total, page, page_size}`
- **Errors:** 401, 403, 500.

```json
{"correlation_id": "...", "items": [{"id": 7, "correlation_id": "...", "username": "finance", "role": "finance_analyst", "question": "Drop the customers table", "stage": "sql_validation", "reason_code": "DDL_STATEMENT", "reason_text": "Only read-only questions are allowed.", "sql_text": null, "created_at": "..."}], "total": 1, "page": 1, "page_size": 20}
```

### `GET /admin/errors`
- **Access:** admin.
- **Request:** query `page`, `page_size`, `status`, `node_name`.
- **Response:** `200 ErrorList {correlation_id, items: [{id, correlation_id, question_id, username, node_name, error_type, retryable, error_message, status, created_at}], total, page, page_size}`
- **Errors:** 401, 403, 500.

```json
{"correlation_id": "...", "items": [{"id": 3, "correlation_id": "...", "question_id": "c3a0...", "username": "finance", "node_name": "N-09", "error_type": "REPAIR_LIMIT", "retryable": false, "error_message": "column \"revenu\" does not exist", "status": "open", "created_at": "..."}], "total": 1, "page": 1, "page_size": 20}
```

### `POST /admin/errors/{id}/rerun`
- **Access:** admin.
- **Request:** path `id`; no body. The question is re-run from the logged input **as the original user**, so the original role and region apply.
- **Response:** `202 RerunResponse {correlation_id, error_id, new_question_id, status}`
- **Errors:** 401, 403, 404, 409 (already re-run), 500.

```json
{"correlation_id": "...", "error_id": 3, "new_question_id": "e1f2...", "status": "ANSWERED"}
```

### `GET /admin/users`
- **Access:** admin.
- **Request:** query `page`, `page_size`, `role`, `is_active`.
- **Response:** `200 UserList {correlation_id, items: [{id, username, display_name, role, regions, is_active, last_login_at}], total, page, page_size}`
- **Errors:** 401, 403, 500.

### `POST /admin/users`
- **Access:** admin.
- **Request:** `CreateUserRequest {username, display_name, password, role: RoleName | null, regions: [RegionCode]}`
- **Response:** `201 UserResponse {correlation_id, id, username, display_name, role, regions, is_active}`
- **Errors:** 400 (weak password, sales manager without a region), 401, 403, 409 (`USERNAME_TAKEN`), 500.

```json
{"username": "sales.nordics", "display_name": "Nordics Sales", "password": "<set by admin>", "role": "sales_manager", "regions": ["EUROPE"]}
```

Design choice: §19 lists only `GET/POST /admin/users`. The other user-management actions
from §8 use two extra endpoints on the same resource:
- `PATCH /admin/users/{id}` with `{is_active?, role?, regions?, display_name?}`: disable,
  enable, assign role and regions. Disabling bumps `token_version`.
- `POST /admin/users/{id}/reset-password` with `{new_password}`: resets the password and
  bumps `token_version`.

Every user-management action is written to the audit log.

### `GET /admin/review`
- **Access:** admin.
- **Request:** query `page`, `page_size`, `kind` (`not_helpful`, `blocked`, `failure`; all when omitted).
- **Response:** `200 ReviewList {correlation_id, items: [{kind, id, question_id, correlation_id, question, username, role, sql_text, detail, status, created_at}], total, page, page_size}`. Open not-helpful answers, blocked queries and open failures in one list, newest first (Step 20).
- **Errors:** 401, 403, 500.

### `GET /admin/verified-queries`
- **Access:** admin.
- **Request:** query `page`, `page_size`, `is_active`.
- **Response:** `200 VerifiedQueryList {correlation_id, items: [{id, lineage_id, version, question_text, sql_text, description, tables_used, metrics_used, allowed_roles, is_active, verified_by, verified_at, source_question_id}], total, page, page_size}`
- **Errors:** 401, 403, 500.

### `POST /admin/verified-queries`
- **Access:** admin.
- **Request:** `VerifyRequest {source_question_id: UUID | null, question_text, sql_text, description, allowed_roles: [RoleName], metrics_used: [str], lineage_id: UUID | null}`. With `lineage_id`, a new version is created (correct) and the older versions are disabled. The SQL must pass the validator for every allowed role; allowed roles cannot be wider than the metrics' roles.
- **Response:** `201 VerifiedQueryResponse {correlation_id, ...the library item}`
- **Errors:** 400 (`SQL_INVALID` with the validation reason, `VALIDATION_ERROR`), 401, 403, 404, 500.

```json
{"source_question_id": "c3a0...", "question_text": "Revenue by month in 2024", "sql_text": "SELECT date_trunc('month', o.order_date) AS month, ...", "description": "Monthly revenue for 2024", "allowed_roles": ["sales_manager", "finance_analyst"], "metrics_used": ["revenue"], "lineage_id": null}
```

### `PATCH /admin/verified-queries/{id}`
- **Access:** admin.
- **Request:** `{is_active: bool}`. Enabling re-validates the SQL and disables the other versions of the lineage.
- **Response:** `200 VerifiedQueryResponse`
- **Errors:** 400, 401, 403, 404, 500.

### `POST /admin/feedback/{id}/eval-case`
- **Access:** admin.
- **Request:** `EvalCaseRequest {case_type, expected_behaviour, expected_sql: str | null}`. The expected SQL is validated for the asking user's role.
- **Response:** `201 EvalCaseResponse {correlation_id, case_id, case_key: "FB-<feedback id>", dataset: "review-cases"}`; the feedback becomes `converted`.
- **Errors:** 400, 401, 403, 404, 409 (already converted), 500.

### `POST /admin/eval/run`
- **Access:** admin.
- **Request:** `EvalRunRequest {dataset: str, dataset_version: int | null, experiment_name: str, verified_examples_enabled: bool, subset: [case_key] | null}`
- **Response:** `202 EvalRunStarted {correlation_id, run_id, status: "running"}` (the run continues in the background).
- **Errors:** 400, 401, 403, 404 (unknown dataset), 409 (a run is already in progress), 500.

```json
{"dataset": "northwind-eval", "dataset_version": null, "experiment_name": "with-verified-examples", "verified_examples_enabled": true, "subset": null}
```

### `GET /admin/eval/runs`
- **Access:** admin.
- **Request:** query `page`, `page_size`; `GET /admin/eval/runs/{id}` returns one run with its failing cases.
- **Response:** `200 EvalRunList {correlation_id, items: [{run_id, experiment_name, model_name, status, execution_accuracy, clarification_rate, unsafe_blocked_rate, access_leaks, ungrounded_answers, latency_p50_ms, latency_p95_ms, avg_cost_usd, started_at, finished_at}], total, page, page_size}`
- **Errors:** 401, 403, 404, 500.

## Endpoint summary

| Method | Path | Access | Source |
| --- | --- | --- | --- |
| POST | `/auth/login` | public | §19 |
| GET | `/health` | public | §19 |
| POST | `/ask` | user with a business role | §19 |
| POST | `/clarify` | question owner | §19 |
| GET | `/conversations` | own | §19 |
| GET | `/conversations/{id}` | own | §19 |
| POST | `/feedback` | question owner | §19 |
| GET | `/admin/metrics` | admin | §19 |
| GET | `/admin/blocked` | admin | §19 |
| GET | `/admin/errors` | admin | §19 |
| POST | `/admin/errors/{id}/rerun` | admin | §19 |
| GET | `/admin/users` | admin | §19 |
| POST | `/admin/users` | admin | §19 |
| PATCH | `/admin/users/{id}` | admin | design choice (§8) |
| POST | `/admin/users/{id}/reset-password` | admin | design choice (§8) |
| GET | `/admin/review` | admin | design choice (§16) |
| GET | `/admin/verified-queries` | admin | §19 |
| POST | `/admin/verified-queries` | admin | §19 |
| PATCH | `/admin/verified-queries/{id}` | admin | design choice (§16) |
| POST | `/admin/feedback/{id}/eval-case` | admin | design choice (§16) |
| POST | `/admin/eval/run` | admin | §19 |
| GET | `/admin/eval/runs` | admin | §19 |
| GET | `/admin/eval/runs/{id}` | admin | design choice (§20) |
