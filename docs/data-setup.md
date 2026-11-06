# Data setup

How the Northwind data is prepared. Decisions and reasons are in
`docs/design/data-decisions.md`; this page describes exactly what the seed does.

## One command

```bash
docker compose up -d          # PostgreSQL 16; loads data/northwind/northwind.sql on first start
python -m scripts.seed        # everything below; safe to run any number of times
```

The seed (`scripts/seed.py`) waits for the database, runs Alembic migrations, then applies
the steps below as the owner role and prints a summary. To reset all data, run
`docker compose down -v`, then the two commands again.

## Date shift

- **Amount:** `+27` years, from `config/app.yaml` (`data_setup.date_shift_years`).
- **Columns:** `orders.order_date`, `orders.required_date`, `orders.shipped_date`,
  `employees.birth_date`, `employees.hire_date`. Employee dates move with the orders so
  hire dates stay before the orders those employees took.
- **How:** `UPDATE ... SET col = (col + make_interval(years => 27))::date`. NULL dates
  (21 unshipped orders) stay NULL. 29 February becomes 28 February in non-leap years.
- **Result:** orders run from **2023-07-04 to 2025-05-06** (originally 1996-07-04 to
  1998-05-06). The business reference date is 2025-05-06.
- **Exactly once:** the shift and a row in `analytics.data_setup`
  (`key = 'date_shift_years'`, `value = '27'`) are written in one transaction, under a
  table lock. A second run sees the row and skips the shift. If the config later asks for
  a different number of years, the seed stops with an error instead of shifting again.
- **Undo:** subtract the same interval, or reset with `docker compose down -v`.

These `UPDATE`s are the only writes to Northwind tables in the project, done once by the
seed as the owner. The application and the agent never write to them.

## Sales regions

- **Source:** `config/regions.yaml` (versioned). Every country is in exactly one region.
- **Tables** (schema `analytics`, owner-only):
  - `sales_regions (code, name)`: `EUROPE` Europe, `AMERICAS` Americas, `ROW` Rest of World;
  - `country_region (country, region_code)`: one row per customer country.
- **Views:** `analytics.customer_regions (customer_id, region_code)` and
  `analytics.order_regions (order_id, customer_id, region_code)`. An order takes its
  **customer's** region (not `ship_country`).
- **Mapping:**

  | Region | Countries | Customers |
  | --- | --- | --- |
  | EUROPE | Austria, Belgium, Denmark, Finland, France, Germany, Ireland, Italy, Norway, Poland, Portugal, Spain, Sweden, Switzerland, UK | 54 |
  | AMERICAS | USA, Canada, Mexico | 21 |
  | ROW | Brazil, Argentina, Venezuela | 16 |

- **Checks:** the seed fails if any customer country has no region. Tests confirm that
  all 91 customers and all 830 orders have exactly one region.

## Sensitive columns

Listed with the roles allowed to see them in `config/access_policy.yaml`
(`sensitive_columns`) and enforced by the secure views. See `docs/access-control.md`.

## Roles and test users

- **Application roles** (`app.roles`): `sales_manager`, `finance_analyst`,
  `operations_manager`, `admin`, from `config/access_policy.yaml`. `db_role` holds the
  role's secure-view schema (`sales_ro`, `finance_ro`, `operations_ro`; none for admin).
- **Test users** (`config/test_users.yaml`, brief section 7):

  | User | Role | Region | Enabled |
  | --- | --- | --- | --- |
  | sales.europe | sales_manager | EUROPE | yes |
  | sales.americas | sales_manager | AMERICAS | yes |
  | sales.other | sales_manager | ROW | yes |
  | finance | finance_analyst | | yes |
  | operations | operations_manager | | yes |
  | admin | admin | | yes |
  | no.role | (none) | | yes |
  | disabled.user | finance_analyst | | **no** |

- **Passwords:** read from `DEMO_PASSWORD_<USERNAME>` (dots become underscores, e.g.
  `DEMO_PASSWORD_SALES_EUROPE`), hashed with argon2. A password is re-hashed only when it
  changes; then `token_version` is bumped so old tokens stop working. Disabling a user also
  bumps it.
- **Upserts:** users by `username`, roles by `name`, one `user_roles` row per user, and
  `user_regions` reset to exactly the configured region. Running twice creates no
  duplicates. Users that are not in the config file are never touched.

## Semantic layer

The seed checks `config/semantic/semantic_layer.yaml` against the database (every table,
column and metric must exist) and syncs it into `app.semantic_catalog` and
`app.metric_definitions`. See Step 7 in `docs/decisions-log.md`.
