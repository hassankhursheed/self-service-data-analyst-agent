# Access control

Brief sections 12, 13 and 27. Data access is enforced by PostgreSQL itself. The agent's SQL
runs with a read-only login that can only read secure views, and the views decide which
rows and columns a user sees from session settings taken from the token, never from the
question.

Everything below is created by the seed script (`python -m scripts.seed`, file
`app/db/setup/access.py`) from `config/access_policy.yaml`. It is idempotent: every run
re-applies the roles and grants and rebuilds the views.

## Login roles

| Role | Created from | Rights |
| --- | --- | --- |
| owner (`POSTGRES_USER`) | Docker Compose | Superuser of the container. Runs migrations and the seed only; never used by the running app or agent. |
| `app_rw` | `APP_DATABASE_URL` | `CONNECT`; `USAGE` on schema `app`; `SELECT, INSERT, UPDATE, DELETE` on `app` tables (default privileges cover tables added by later migrations). No access to `public`, `analytics` or the view schemas; cannot change `app.alembic_version`. |
| `analytics_ro` | `ANALYTICS_DATABASE_URL` | `CONNECT`; `USAGE` and `SELECT` on the three view schemas only. `default_transaction_read_only = on`, role-level `statement_timeout` (config `analytics.role_statement_timeout_ms`). |

Both login roles are `NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION
NOBYPASSRLS`. User names and passwords come from the two connection strings in the
environment; nothing is hard-coded.

Locked down for everyone (`PUBLIC`):
- `CONNECT` and `TEMP` on the database are revoked (so no temporary tables).
- All rights on schemas `public` and `analytics` and their tables are revoked; the
  roles have no `CREATE` anywhere, so they cannot create tables, views or functions.
- `EXECUTE` on `pg_catalog.set_config(text, text, boolean)` is revoked, so a query cannot
  rewrite its own session settings from inside a `SELECT`. Both login roles run with
  `jit = off`, and the engines tell asyncpg so it never needs `set_config` for type
  introspection (docs/audit-and-tracing.md).

## Secure views

One schema per business role, rebuilt from `config/access_policy.yaml`:

| View schema | Business role | Tables |
| --- | --- | --- |
| `sales_ro` | `sales_manager` | customers, orders, order_details, products, categories, suppliers, shippers, employees |
| `finance_ro` | `finance_analyst` | same eight tables |
| `operations_ro` | `operations_manager` | same eight tables |
| (none) | `admin` | no business data |

Each view is `WITH (security_barrier = true)`, owned by the owner, and:
1. **selects only the columns the role may see** (sensitive columns are left out of the
   view, so `SELECT *` cannot reveal them and naming one is an error);
2. **checks the role:** `current_setting('app.user_role', true) = '<role>'`;
3. **for `sales_ro`, filters rows by region** (row-level security through views):
   - `customers`: `customer_id IN (SELECT customer_id FROM analytics.customer_regions WHERE region_code = current_setting('app.user_region', true))`
   - `orders`, `order_details`: the same with `order_id` and `analytics.order_regions`.

`security_barrier` stops a user-supplied condition from seeing rows before the view's
own filter runs. If a session setting is missing, `current_setting(..., true)` returns
NULL and the view returns **no rows** (fail closed). A sales user querying
`finance_ro.orders` also gets no rows, because the role check fails.

Why views and not RLS policies on the base tables: one read-only login serves every
user, and column visibility differs per role. Views give per-role columns and rows in
one place, and `analytics_ro` never needs rights on the raw tables.

## Sensitive columns by role

From `config/access_policy.yaml` (`sensitive_columns`):

| Columns | sales_manager | finance_analyst | operations_manager |
| --- | --- | --- | --- |
| `employees`: address, city, region, postal_code, country, home_phone, extension, birth_date, notes, photo, photo_path | hidden | hidden | hidden |
| `customers`: contact_name, contact_title, phone, fax, address, postal_code | visible (own region) | hidden | hidden |
| `suppliers`: contact_name, contact_title, phone, fax, address, homepage | hidden | hidden | visible |
| `categories`: picture | hidden | hidden | hidden |
| all other columns of the eight tables | visible | visible | visible |

Not exposed to any role: `territories`, `employee_territories`, `region`, `us_states`,
`customer_customer_demo`, `customer_demographics`.

## Running a query: `app/db/analytics.py`

`run_readonly(sql, user_ctx, timeout_ms, row_limit)` takes a `UserContext` (username,
role, region; built from the token in a later step, never from user text) and:

1. opens a `READ ONLY` transaction on a pooled `analytics_ro` connection;
2. runs, with values taken only from validated enums:
   ```sql
   SET LOCAL statement_timeout = <timeout_ms>;
   SET LOCAL search_path = "sales_ro";          -- the role's view schema
   SET LOCAL app.user_role = 'sales_manager';
   SET LOCAL app.user_region = 'EUROPE';        -- sales managers only
   ```
3. sends the query as a **prepared statement**, so only one statement can run
   (`SET ...; SELECT ...` is rejected);
4. fetches at most `row_limit + 1` rows through a cursor and reports `truncated`;
5. maps errors to stable codes: `timeout`, `permission_denied`, `read_only`, `db_error`,
   `no_data_access` (admin), `invalid_limit`.

`SET LOCAL` lasts only for the transaction, so a pooled connection never carries one
user's role or region into another user's query.

## What the tests prove (`tests/integration/test_access_control.py`)

- `sales.europe`, `sales.americas` and `sales.other` each see only their region's orders,
  customers and order lines; the three regional totals add up to the finance total.
- `finance` sees all 830 orders but no employee personal columns.
- `operations` sees products, suppliers and shipping, but no customer contact columns.
- `analytics_ro` cannot `INSERT`, `UPDATE`, `DELETE`, `CREATE` (tables, temp tables,
  functions), read raw `public` tables or read the `app` schema, even with read-only mode
  switched off.
- Missing session settings return zero rows.
- `set_config(...)` inside a query is refused, and `SET ...; SELECT ...` is rejected, so a
  query cannot change its own region; the user's results stay the same afterwards.
- Admin has no business data access; the row limit and statement timeout are enforced.
