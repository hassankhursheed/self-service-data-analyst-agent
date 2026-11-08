# SQL safety

Brief section 12. Generated SQL passes **two independent layers** before any data comes back:

1. **Code: the SQL validator** (`app/safety/sql_validator.py`, this page). It refuses
   anything that is not one safe, read-only SELECT over what the user's role may use, and
   gives the user a plain-language reason.
2. **Database: the read-only role** (`docs/access-control.md`). Even if the validator had a
   bug, `analytics_ro` cannot write, create objects, change its own role or region, or
   read hidden columns, other regions or the application schema.

Both layers are required. The validator gives clear reasons and stops bad queries before
they reach the database; the database makes the guarantee that does not depend on code.

## How a query is checked

`validate(sql, role, semantic_layer)` returns a `SqlValidationResult` with `allowed`,
`reason_code` (one `BlockReason`), `user_message`, `detail` (for logs), the `tables` and
`table.column` names used, the `original_sql` and the `final_sql`. Only `final_sql` is ever
executed.

Everything is decided on the **parse tree** (sqlglot, PostgreSQL dialect), not with
regular expressions. `final_sql` is regenerated from the checked tree **without
comments**, so text hidden in comments or odd formatting never reaches the database.

| # | Rule | Reason code | Why |
| --- | --- | --- | --- |
| 1 | The role must have business tables (admin and no-role users have none). | `NO_DATA_ACCESS` | Brief §8 and §13: no business data for these users. |
| 2 | The query must not be empty. | `EMPTY_SQL` | Nothing to run. |
| 3 | It must parse as PostgreSQL. | `PARSE_ERROR` | What cannot be parsed cannot be checked, so it is never run. |
| 4 | Exactly one statement. `SELECT 1; DROP TABLE x` and a statement hidden after a comment (`... /* x */; DROP ...`) are two statements. | `MULTIPLE_STATEMENTS` | Prevents a harmless query from carrying a second, harmful one. |
| 5 | No `INSERT`, `UPDATE`, `DELETE` or `MERGE` anywhere, including data-changing CTEs (`WITH x AS (DELETE ...) SELECT ...`). | `WRITE_STATEMENT` | The assistant only reads data. |
| 6 | No `CREATE`, `DROP`, `ALTER`, `TRUNCATE` (tables, views, functions, anything). | `DDL_STATEMENT` | The schema must never change. |
| 7 | No `GRANT` or `REVOKE`. | `PERMISSION_STATEMENT` | Access rights are managed by the seed only. |
| 8 | No `SET` (including `SET LOCAL`). | `SET_STATEMENT` | Session settings carry the user's role and region. |
| 9 | No `COPY`, including `COPY ... PROGRAM`. | `COPY_STATEMENT` | Reads or writes server files and can run programs. |
| 10 | No `CALL`, `DO`, `EXECUTE`. | `PROCEDURE_CALL` | Runs code outside the checked SELECT. |
| 11 | Only a query (`SELECT`, `WITH ... SELECT`, `UNION` / `INTERSECT` / `EXCEPT` of selects). `EXPLAIN`, `BEGIN`, `VACUUM`, `LOCK` and other commands are refused. | `NOT_SELECT` | One read-only query is the only allowed shape. |
| 12 | No `SELECT ... INTO`. | `SELECT_INTO` | It creates a table. |
| 13 | No `FOR UPDATE` / `FOR SHARE`. | `LOCKING_CLAUSE` | Locks rows other users need. |
| 14 | No system catalogs: schemas `pg_catalog`, `information_schema`, `pg_toast`, any `pg_*` table name, and casts to `reg*` types (`'x'::regclass`). | `SYSTEM_CATALOG` | Catalogs reveal users, roles, settings and table structure. |
| 15 | Table names must be plain (`orders`, not `finance_ro.orders` or `public.orders`). | `SCHEMA_QUALIFIED` | The executor points `search_path` at the role's view schema; a qualified name could aim at another role's views or raw tables. |
| 16 | Every table (other than a CTE name) must be allowed for the role in the semantic layer. | `TABLE_NOT_ALLOWED` | Per-role table allow-list (brief §9, §12). |
| 17 | Every column must be allowed for the role, wherever it appears: select list, `WHERE`, `ORDER BY`, functions, joins, subqueries, CTEs and aliases. | `COLUMN_NOT_ALLOWED` | Hidden columns must not leak through any path. |
| 18 | `SELECT *` and `t.*` are **expanded** to the role's allowed columns only. | (rewrite) | `*` can never pull in a hidden column, even one added to the table later. |
| 19 | Only allow-listed functions (`config/sql_policy.yaml`): aggregates, window, conditional, maths, date and text functions. Everything else is refused, e.g. `set_config`, `current_setting`, `pg_sleep`, `pg_read_file`, `lo_import`, `dblink`, `query_to_xml`, `version()`, `generate_series`, unknown names. | `FORBIDDEN_FUNCTION` | An allow-list fails safe: a dangerous function nobody thought of is still blocked. |
| 20 | No functions that read the real clock: `now()`, `current_date`, `current_timestamp`, `localtimestamp`, `clock_timestamp()`, `age(x)`. | `REAL_DATE_FUNCTION` | Dates come from the business calendar (`docs/business-calendar.md`), so answers are repeatable. |
| 21 | Outer `LIMIT`: added when missing (`default_limit` = 200), lowered when above `max_limit` (1000), `LIMIT ALL` becomes `max_limit`. Inner `LIMIT`s are kept. | (rewrite) | Large results are capped before they are fetched. |
| 22 | `LIMIT` must be a plain number; `LIMIT $1`, `LIMIT 10 + 5` and `FETCH FIRST` are refused. | `INVALID_LIMIT` | Only a literal can be checked against the maximum. |

### How hidden columns are caught

The validator builds a schema containing **only** the tables and columns the role may
use (from the semantic layer, which is itself never wider than
`config/access_policy.yaml`), then asks sqlglot to qualify every column against it. A
column outside that schema cannot be resolved, however it is reached, for example:

| Query (operations role) | Result |
| --- | --- |
| `SELECT contact_name FROM customers` | blocked, `COLUMN_NOT_ALLOWED` |
| `SELECT x.who FROM (SELECT c.contact_name AS who FROM customers c) x` | blocked |
| `WITH p AS (SELECT phone FROM customers) SELECT * FROM p` | blocked |
| `SELECT company_name FROM customers ORDER BY phone` | blocked |
| `SELECT * FROM customers` | allowed; rewritten to the allowed columns, without `contact_name` or `phone` |

Because the allow-list comes from the semantic layer, a column that the database view
exposes but the semantic layer does not describe (for example `orders.ship_address`) is
also refused. To make such a column usable, describe it in
`config/semantic/semantic_layer.yaml`.

### String and comment tricks

- `SELECT ... WHERE company_name = 'x; DROP TABLE orders'` is allowed: the text is a string
  value, not a statement. Dollar-quoted strings are re-written as normal escaped strings.
- `SELECT ... -- ; DROP TABLE orders` is allowed, and `final_sql` has no comment.
- `SELECT ... /* note */; DROP TABLE orders` is two statements and is blocked.

## Cost check before running (Step 26)

After validation, `run_readonly` asks PostgreSQL for the plan (`EXPLAIN (FORMAT JSON)`,
inside the same read-only transaction and role scope; nothing is executed). A query whose
estimated total cost is above `analytics.max_plan_cost` (10,000) is not run: it ends
`BLOCKED` with `TOO_EXPENSIVE`, is stored in `blocked_queries` with the estimate, and is
not sent to repair. Measured on the seeded data: every verified example costs under 700; a
cross join of `orders` and `order_details` costs about 14,000 (sales views) to 27,000
(finance). The statement timeout stays as the second line of defence.

## Question check

`validate_question(text)` (`app/safety/question_check.py`) runs before anything else:
empty or whitespace-only questions are `QUESTION_EMPTY`; questions longer than
`max_question_length` (500 characters) are `QUESTION_TOO_LONG`. The question is trimmed.
The user's text is never executed as SQL.

## Reason codes

All codes are in one enum, `BlockReason` (`app/core/enums.py`), each with one user message
in `app/safety/sql_policy.py` (a test checks every code has a message). They will be
stored in `app.blocked_queries.reason_code` and counted on the monitoring dashboard.

## Configuration

`config/sql_policy.yaml` (versioned): `max_question_length`, `default_limit`,
`max_limit`, `allowed_functions` (sqlglot function keys, e.g. `date_trunc` is
`timestamptrunc`) and `allowed_anonymous_functions` (e.g. `make_date`).

## Tests

- `tests/unit/test_sql_validator.py` (92 tests): every blocked category above, valid CTE,
  window, UNION and multi-join revenue queries, hidden columns through aliases, CTEs,
  `WHERE`, `ORDER BY` and `SELECT *`, a comment-hidden second statement, and all LIMIT
  cases.
- `tests/integration/test_validator_db.py`: validated `final_sql` runs through
  `run_readonly`, expanded `*` hides columns in real results, region filters still apply,
  and the database refuses a hidden column even without the validator.
