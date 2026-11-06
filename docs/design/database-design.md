# Database design

Brief sections 6, 12, 13, 21 and 27. One PostgreSQL database, four schemas:

| Schema | Contents | Written by |
| --- | --- | --- |
| `public` | Northwind tables (loaded from the dump, dates shifted) | seed script only |
| `analytics` | `sales_regions`, `country_region` mapping | seed script only |
| `app` | application tables below (Alembic migrations) | the application (`app_rw`) |
| `checkpoints` | LangGraph checkpointer tables (managed by the library) | the application |

## Application ERD (`app` schema)

Region codes in `app.user_regions` are a CHECK constraint (not a foreign key), so Alembic never depends on a schema outside `app`.

Conventions: UUID primary keys for user-facing rows, `bigint` identity keys for high-volume
logs; every table has `created_at timestamptz` (and `updated_at` where rows change).
Status and type columns are `text` with CHECK constraints. Small lists use `text[]`; there
is no catch-all JSON blob (JSONB is used only for masked input/output summaries).

<!-- erd:start -->
```mermaid
erDiagram
    questions |o--o{ agent_errors : "question_id"
    agent_runs |o--o{ agent_errors : "run_id"
    questions ||--o{ agent_runs : "question_id"
    agent_runs ||--o{ agent_steps : "run_id"
    users |o--o{ audit_log : "actor_user_id"
    generated_queries |o--o{ blocked_queries : "generated_query_id"
    agent_runs ||--o{ blocked_queries : "run_id"
    questions ||--o{ clarifications : "question_id"
    users ||--o{ conversations : "user_id"
    eval_datasets ||--o{ eval_cases : "dataset_id"
    feedback |o--o{ eval_cases : "source_feedback_id"
    eval_cases ||--o{ eval_results : "case_id"
    questions |o--o{ eval_results : "question_id"
    eval_runs ||--o{ eval_results : "run_id"
    eval_datasets ||--o{ eval_runs : "dataset_id"
    users |o--o{ eval_runs : "started_by"
    questions ||--o{ feedback : "question_id"
    users ||--o{ feedback : "user_id"
    agent_runs ||--o{ generated_queries : "run_id"
    users |o--o{ metric_definitions : "updated_by"
    generated_queries ||--o{ query_executions : "generated_query_id"
    conversations ||--o{ questions : "conversation_id"
    questions |o--o{ questions : "parent_question_id"
    users ||--o{ questions : "user_id"
    users |o--o{ user_regions : "assigned_by"
    users ||--o{ user_regions : "user_id"
    users |o--o{ user_roles : "assigned_by"
    roles ||--o{ user_roles : "role_id"
    users ||--o{ user_roles : "user_id"
    questions |o--o{ verified_queries : "source_question_id"
    users |o--o{ verified_queries : "verified_by"
    agent_errors {
        bigint id PK
        uuid correlation_id
        uuid question_id FK
        uuid run_id FK
        varchar node_name
        varchar error_type
        boolean retryable
        text error_message
        jsonb input_snapshot
        varchar status
        timestamptz updated_at
        timestamptz created_at
    }
    agent_runs {
        uuid id PK
        uuid question_id FK
        integer run_number
        uuid correlation_id
        varchar graph_version
        varchar prompt_version
        varchar semantic_version
        varchar model_name
        varchar final_status
        integer total_latency_ms
        integer input_tokens
        integer output_tokens
        numeric estimated_cost_usd
        text langsmith_trace_url
        timestamptz started_at
        timestamptz finished_at
        timestamptz created_at
    }
    agent_steps {
        bigint id PK
        uuid run_id FK
        integer seq
        varchar node_name
        varchar from_status
        varchar to_status
        jsonb input_summary
        jsonb output_summary
        integer latency_ms
        varchar error_code
        timestamptz started_at
        timestamptz created_at
    }
    alerts {
        bigint id PK
        varchar alert_type
        numeric metric_value
        numeric threshold
        text message
        varchar channel
        timestamptz sent_at
        timestamptz created_at
    }
    audit_log {
        bigint id PK
        timestamptz occurred_at
        uuid correlation_id
        uuid actor_user_id FK
        varchar event_type
        varchar target_type
        varchar target_id
        jsonb details
        inet client_ip
        timestamptz created_at
    }
    blocked_queries {
        bigint id PK
        uuid run_id FK
        bigint generated_query_id FK
        varchar stage
        varchar reason_code
        text reason_text
        timestamptz created_at
    }
    business_calendar_config {
        smallint id PK
        integer version UK
        date reference_date
        varchar time_zone
        smallint fiscal_year_start_month
        varchar week_start
        boolean is_active
        timestamptz created_at
    }
    clarifications {
        bigint id PK
        uuid question_id FK
        text asked_text
        text_array options
        text answer_text
        timestamptz answered_at
        timestamptz created_at
    }
    conversations {
        uuid id PK
        uuid user_id FK
        varchar title
        boolean is_archived
        timestamptz updated_at
        timestamptz created_at
    }
    eval_cases {
        bigint id PK
        smallint dataset_id FK
        varchar case_key
        varchar case_type
        varchar test_username
        text question
        varchar expected_behaviour
        text expected_sql
        bigint source_feedback_id FK
        timestamptz updated_at
        timestamptz created_at
    }
    eval_datasets {
        smallint id PK
        varchar name
        integer version
        text file_path
        varchar langsmith_dataset_id
        timestamptz created_at
    }
    eval_results {
        bigint id PK
        uuid run_id FK
        bigint case_id FK
        uuid question_id FK
        boolean passed
        varchar final_status
        text failure_reason
        integer latency_ms
        numeric cost_usd
        timestamptz created_at
    }
    eval_runs {
        uuid id PK
        smallint dataset_id FK
        varchar experiment_name
        varchar model_name
        numeric temperature
        varchar graph_version
        varchar prompt_version
        varchar semantic_version
        boolean verified_examples_enabled
        date reference_date
        varchar status
        numeric execution_accuracy
        numeric clarification_rate
        numeric unsafe_blocked_rate
        integer access_leaks
        integer ungrounded_answers
        integer latency_p50_ms
        integer latency_p95_ms
        numeric avg_cost_usd
        uuid started_by FK
        timestamptz started_at
        timestamptz finished_at
        timestamptz updated_at
        timestamptz created_at
    }
    feedback {
        bigint id PK
        uuid question_id FK
        uuid user_id FK
        varchar rating
        text comment
        varchar review_status
        timestamptz updated_at
        timestamptz created_at
    }
    generated_queries {
        bigint id PK
        uuid run_id FK
        integer attempt
        varchar kind
        text sql_text
        text_array tables_used
        text_array metrics_used
        varchar confidence
        date date_from
        date date_to
        uuid_array verified_query_ids
        timestamptz created_at
    }
    metric_definitions {
        bigint id PK
        varchar name
        text definition_sql
        text_array tables
        text join_condition
        text_array synonyms
        text_array allowed_roles
        integer version
        boolean is_active
        uuid updated_by FK
        timestamptz updated_at
        timestamptz created_at
    }
    query_executions {
        bigint id PK
        bigint generated_query_id FK
        varchar db_role
        varchar region_code
        varchar status
        integer row_count
        integer result_bytes
        integer latency_ms
        text error_message
        timestamptz executed_at
        timestamptz created_at
    }
    questions {
        uuid id PK
        uuid correlation_id UK
        uuid conversation_id FK
        uuid user_id FK
        uuid parent_question_id FK
        text question_text
        varchar role_name
        varchar region_code
        varchar status
        date resolved_date_from
        date resolved_date_to
        text_array assumptions
        timestamptz completed_at
        timestamptz updated_at
        timestamptz created_at
    }
    roles {
        smallint id PK
        varchar name UK
        varchar db_role
        text description
        timestamptz created_at
    }
    semantic_catalog {
        bigint id PK
        varchar object_type
        varchar object_name
        text description
        text_array example_values
        text_array allowed_roles
        integer version
        boolean is_active
        timestamptz updated_at
        timestamptz created_at
    }
    user_regions {
        uuid user_id PK, FK
        varchar region_code PK
        uuid assigned_by FK
        timestamptz created_at
    }
    user_roles {
        uuid user_id PK, FK
        smallint role_id FK
        uuid assigned_by FK
        timestamptz created_at
    }
    users {
        uuid id PK
        varchar username UK
        text password_hash
        varchar display_name
        boolean is_active
        integer token_version
        timestamptz last_login_at
        timestamptz updated_at
        timestamptz created_at
    }
    verified_queries {
        uuid id PK
        uuid lineage_id
        integer version
        text question_text
        text sql_text
        text description
        uuid source_question_id FK
        boolean is_active
        uuid verified_by FK
        timestamptz verified_at
        timestamptz updated_at
        timestamptz created_at
    }
```
<!-- erd:end -->

The ERD above is generated from the SQLAlchemy models (`python scripts/generate_erd.py`), and a unit test fails if it drifts. Relationship labels are the foreign-key columns; `||` means required, `|o` optional. `text_array` and `uuid_array` stand for `text[]` and `uuid[]` (Mermaid cannot show brackets). Status and type columns are limited by CHECK constraints backed by `app/core/enums.py`.

### Unique constraints and indexes

| Table | Unique constraints | Indexes (besides PK/FK) |
| --- | --- | --- |
| users | `username` | |
| roles | `name` | |
| user_roles | `user_id` (one role per user) | `role_id` |
| user_regions | PK `(user_id, region_code)`; CHECK `region_code` in `EUROPE`, `AMERICAS`, `ROW` | |
| conversations | | `(user_id, updated_at DESC)` |
| questions | `correlation_id` | `(conversation_id, created_at)`, `(status, created_at)`, `(user_id, created_at)` |
| agent_runs | `(question_id, run_number)` | `(correlation_id)`, `(started_at)`, `(final_status, started_at)` |
| agent_steps | `(run_id, seq)` | `(node_name, started_at)` |
| generated_queries | `(run_id, attempt)` | |
| query_executions | | `(generated_query_id)`, `(status, executed_at)` |
| blocked_queries | | `(run_id)`, `(reason_code, created_at)` |
| clarifications | | `(question_id)` |
| feedback | `(question_id, user_id)` | `(rating, review_status)` |
| semantic_catalog | `(object_type, object_name, version)`; partial unique `(object_type, object_name) WHERE is_active` | |
| metric_definitions | `(name, version)`; partial unique `(name) WHERE is_active` | |
| business_calendar_config | `version`; partial unique `(is_active) WHERE is_active` | |
| verified_queries | `(lineage_id, version)`; partial unique `(lineage_id) WHERE is_active` | `(is_active)` |
| eval_datasets | `(name, version)` | |
| eval_cases | `(dataset_id, case_key)` | `(case_type)` |
| eval_runs | | `(started_at)`, `(status)` |
| eval_results | `(run_id, case_id)` | `(passed)` |
| audit_log | | `(occurred_at)`, `(event_type, occurred_at)`, `(correlation_id)`, `(actor_user_id)` |
| agent_errors | | `(status, created_at)`, `(correlation_id)` |
| alerts | | `(alert_type, created_at)` |

## Access plan

### Database roles

| Role | Login | Purpose and rights |
| --- | --- | --- |
| `owner` | yes | Owns all schemas; runs the seed script and Alembic migrations. Never used by the running app. |
| `app_rw` | yes | Used by the API for application data: SELECT, INSERT, UPDATE, DELETE on `app` and `checkpoints` only. No rights on `public` or `analytics`. |
| `agent_login` | yes | Read-only login used by N-08. No direct table rights; it is a member of the three group roles below and can only switch to them. Default `default_transaction_read_only = on`. |
| `sales_ro` | no | SELECT on allowed Northwind columns; rows filtered by region (RLS). |
| `finance_ro` | no | SELECT on all order and financial data; no employee personal data. |
| `operations_ro` | no | SELECT on products, suppliers, shipping; no customer contact details. |

No role has INSERT, UPDATE, DELETE, TRUNCATE, CREATE or function-creation rights on
`public` or `analytics`. `CONNECT` is revoked from `PUBLIC`, and `CREATE` on schema
`public` is revoked from everyone except `owner`.

### How role and region reach the session

N-08 runs every query in its own transaction:

```sql
BEGIN READ ONLY;
SET LOCAL ROLE sales_ro;                 -- from the token's role, mapped in app.roles.db_role
SET LOCAL app.region = 'EUROPE';         -- from the token, verified against app.user_regions
SET LOCAL statement_timeout = '10s';     -- from config
<validated SELECT with LIMIT>;
COMMIT;
```

- Both values are bound as parameters (`set_config('app.region', $1, true)`), never built
  from the question text.
- `SET LOCAL` lasts only for the transaction, so a pooled connection never keeps another
  user's role or region.
- Admins and users with no role never reach N-08 (rejected in N-01).

### Row-level security policies

RLS is enabled (and `FORCE`d) on `customers`, `orders` and `order_details`. Other Northwind
tables contain no regional data and are controlled by grants only.

| Table | Role | Policy (`USING`) |
| --- | --- | --- |
| `customers` | `sales_ro` | `country IN (SELECT country FROM analytics.country_region WHERE region_code = current_setting('app.region', true))` |
| `orders` | `sales_ro` | `customer_id IN (SELECT customer_id FROM customers)` (inherits the customers policy) |
| `order_details` | `sales_ro` | `order_id IN (SELECT order_id FROM orders)` (inherits the orders policy) |
| all three | `finance_ro`, `operations_ro` | `true` |

If `app.region` is unset, `current_setting(..., true)` returns NULL and the policy matches no
rows (fail closed). Policies are `SELECT`-only; there are no write policies.

### Sensitive columns by role

Enforced with column-level `GRANT SELECT (col, ...)`. A query that names a hidden column
fails in N-07 (allow-list) and would also fail in the database.

| Table: sensitive columns | `sales_ro` | `finance_ro` | `operations_ro` |
| --- | --- | --- | --- |
| `employees`: address, city, region, postal_code, country, home_phone, extension, birth_date, notes, photo, photo_path | hidden | hidden | hidden |
| `employees`: employee_id, first_name, last_name, title, title_of_courtesy, hire_date, reports_to | visible | visible | visible |
| `customers`: contact_name, contact_title, phone, fax, address, postal_code | visible (own region only) | hidden | hidden |
| `customers`: customer_id, company_name, city, region, country | visible (own region only) | visible | visible |
| `suppliers`: contact_name, contact_title, phone, fax, address, homepage | hidden | hidden | visible |
| `orders`, `order_details` | visible (own region only) | visible | visible |
| `products`, `categories` (except `picture`), `shippers` | visible | visible | visible |
| `territories`, `employee_territories`, `region`, `us_states` | hidden | hidden | hidden |

`categories.picture` and `employees.photo` are binary and never exposed. The
`customer_customer_demo` and `customer_demographics` tables are empty and not granted.
