"""Code-level SQL gate: every generated query must pass ``validate`` before it runs.

Works together with the database layer (docs/access-control.md); both must allow a query.
All checks are done on the sqlglot parse tree (PostgreSQL dialect), not with regex, and
``final_sql`` is regenerated from that tree, so comments and formatting tricks never reach
the database. Rules and reasons: docs/sql-safety.md.
"""

from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlglot import exp, parse
from sqlglot.errors import OptimizeError, SqlglotError
from sqlglot.optimizer.qualify import qualify

from app.core.enums import BlockReason, RoleName
from app.safety.sql_policy import BLOCK_MESSAGES, SqlPolicy, get_sql_policy
from app.semantic.models import SemanticLayer

DIALECT = "postgres"

_STATEMENT_REASONS: tuple[tuple[type[exp.Expression], BlockReason], ...] = (
    (exp.Insert, BlockReason.WRITE_STATEMENT),
    (exp.Update, BlockReason.WRITE_STATEMENT),
    (exp.Delete, BlockReason.WRITE_STATEMENT),
    (exp.Merge, BlockReason.WRITE_STATEMENT),
    (exp.TruncateTable, BlockReason.DDL_STATEMENT),
    (exp.Create, BlockReason.DDL_STATEMENT),
    (exp.Drop, BlockReason.DDL_STATEMENT),
    (exp.Alter, BlockReason.DDL_STATEMENT),
    (exp.Grant, BlockReason.PERMISSION_STATEMENT),
    (exp.Revoke, BlockReason.PERMISSION_STATEMENT),
    (exp.Copy, BlockReason.COPY_STATEMENT),
    (exp.Set, BlockReason.SET_STATEMENT),
    (exp.Transaction, BlockReason.NOT_SELECT),
    (exp.Commit, BlockReason.NOT_SELECT),
    (exp.Rollback, BlockReason.NOT_SELECT),
)

# Functions that read the real clock; dates must come from the business calendar.
_REAL_DATE_FUNCTIONS = {
    "currentdate",
    "currenttimestamp",
    "currenttime",
    "localtimestamp",
    "localtime",
    "currentdatetime",
}
_REAL_DATE_ANONYMOUS = {"now", "clock_timestamp", "statement_timestamp", "transaction_timestamp",
                        "timeofday", "age"}  # fmt: skip
_SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}


class SqlValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason_code: BlockReason | None = None
    user_message: str | None = None
    detail: str | None = None
    tables: list[str] = []
    columns: list[str] = []
    original_sql: str
    final_sql: str | None = None


class _Blocked(Exception):
    def __init__(self, reason: BlockReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _role_schema(layer: SemanticLayer, role: RoleName) -> dict[str, dict[str, str]]:
    """Tables and columns the role may use, as a sqlglot schema (types are not needed)."""
    return {
        t_name: {c_name: "TEXT" for c_name, c in table.columns.items() if role in c.allowed_roles}
        for t_name, table in layer.tables.items()
        if role in table.allowed_roles
    }


def _parse_single(sql: str) -> exp.Expression:
    try:
        statements = [s for s in parse(sql, read=DIALECT) if s is not None]
    except SqlglotError as err:
        raise _Blocked(BlockReason.PARSE_ERROR, str(err).splitlines()[0]) from err
    if not statements:
        raise _Blocked(BlockReason.EMPTY_SQL, "no statement found")
    if len(statements) > 1:
        kinds = ", ".join(type(s).__name__.upper() for s in statements)
        raise _Blocked(BlockReason.MULTIPLE_STATEMENTS, f"{len(statements)} statements: {kinds}")
    return cast(exp.Expression, statements[0])


def _check_statement_types(tree: exp.Expression) -> None:
    if isinstance(tree, exp.Command):
        keyword = str(tree.this).upper()
        reason = (
            BlockReason.PROCEDURE_CALL
            if keyword in {"CALL", "DO", "EXECUTE"}
            else BlockReason.NOT_SELECT
        )
        raise _Blocked(reason, f"{keyword} statement")
    for node in tree.walk():
        for node_type, reason in _STATEMENT_REASONS:
            if isinstance(node, node_type):
                raise _Blocked(reason, f"{type(node).__name__.upper()} found")
    if not isinstance(tree, exp.Query):
        raise _Blocked(BlockReason.NOT_SELECT, f"{type(tree).__name__} is not a SELECT")
    for select in tree.find_all(exp.Select):
        if select.args.get("into"):
            raise _Blocked(BlockReason.SELECT_INTO, "SELECT ... INTO")
        if select.args.get("locks"):
            raise _Blocked(BlockReason.LOCKING_CLAUSE, "FOR UPDATE / FOR SHARE")


def _function_name(node: exp.Func) -> tuple[str, bool]:
    """(name, is_anonymous) for a parsed function call."""
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower(), True
    return node.key.lower(), False


def _check_functions(tree: exp.Expression, policy: SqlPolicy) -> None:
    # Casts to object-identifier types (regclass, regproc, ...) read the system catalogs.
    for data_type in tree.find_all(exp.DataType):
        if data_type.sql(DIALECT).lower().startswith("reg"):
            raise _Blocked(BlockReason.SYSTEM_CATALOG, f"cast to {data_type.sql(DIALECT)}")
    for node in tree.find_all(exp.Func):
        name, anonymous = _function_name(node)
        if (anonymous and name in _REAL_DATE_ANONYMOUS) or (
            not anonymous and name in _REAL_DATE_FUNCTIONS
        ):
            raise _Blocked(BlockReason.REAL_DATE_FUNCTION, f"{name} reads the real clock")
        allowed = (
            name in policy.allowed_anonymous_functions
            if anonymous
            else name in policy.allowed_functions
        )
        if not allowed:
            raise _Blocked(BlockReason.FORBIDDEN_FUNCTION, f"function {name} is not allowed")


def _check_tables(tree: exp.Expression, allowed: dict[str, dict[str, str]]) -> list[str]:
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        schema = (table.db or "").lower()
        if schema in _SYSTEM_SCHEMAS or schema.startswith("pg_") or name.startswith("pg_"):
            raise _Blocked(BlockReason.SYSTEM_CATALOG, f"{table.sql(DIALECT)} is a system table")
        if name in {"information_schema"}:
            raise _Blocked(BlockReason.SYSTEM_CATALOG, "information_schema")
        if schema or table.catalog:
            raise _Blocked(BlockReason.SCHEMA_QUALIFIED, f"{table.sql(DIALECT)} is qualified")
        if not name:
            raise _Blocked(BlockReason.FORBIDDEN_FUNCTION, "table function in FROM")
        if name in cte_names:
            continue
        if name not in allowed:
            raise _Blocked(BlockReason.TABLE_NOT_ALLOWED, f"table {name} is not allowed")
        tables.add(name)
    return sorted(tables)


def _qualify_columns(
    tree: exp.Expression, allowed: dict[str, dict[str, str]]
) -> tuple[exp.Expression, list[str]]:
    """Resolve every column against the role's allowed columns; expand ``*``."""
    schema: dict[str, object] = dict(allowed)
    try:
        qualified = qualify(
            tree,
            schema=schema,
            dialect=DIALECT,
            expand_stars=True,
            validate_qualify_columns=True,
            identify=False,
            quote_identifiers=False,
        )
    except OptimizeError as err:
        raise _Blocked(BlockReason.COLUMN_NOT_ALLOWED, str(err).split(". Line")[0]) from err
    aliases: dict[str, str] = {}
    for table in qualified.find_all(exp.Table):
        if table.name.lower() in allowed:
            aliases[table.alias_or_name.lower()] = table.name.lower()
    columns: set[str] = set()
    for column in qualified.find_all(exp.Column):
        base = aliases.get(column.table.lower())
        if base is None:
            continue  # a CTE, subquery or output alias; its sources were checked
        if column.name.lower() not in allowed[base]:
            raise _Blocked(BlockReason.COLUMN_NOT_ALLOWED, f"{base}.{column.name} is not allowed")
        columns.add(f"{base}.{column.name.lower()}")
    return qualified, sorted(columns)


def _apply_limit(tree: exp.Expression, policy: SqlPolicy) -> exp.Expression:
    if not isinstance(tree, exp.Query):
        return tree
    if tree.args.get("fetch"):
        raise _Blocked(BlockReason.INVALID_LIMIT, "FETCH FIRST is not supported; use LIMIT")
    limit = tree.args.get("limit")
    if limit is None:
        return tree.limit(policy.default_limit, copy=False)
    if isinstance(limit, exp.Fetch) or limit.expression is None:
        raise _Blocked(BlockReason.INVALID_LIMIT, "FETCH FIRST is not supported; use LIMIT")
    value = limit.expression
    if isinstance(value, exp.Literal) and value.is_int:
        if int(value.this) > policy.max_limit:
            return tree.limit(policy.max_limit, copy=False)
        return tree
    if isinstance(value, exp.Null) or (isinstance(value, exp.Var) and value.name.upper() == "ALL"):
        return tree.limit(policy.max_limit, copy=False)
    raise _Blocked(BlockReason.INVALID_LIMIT, f"LIMIT {value.sql(DIALECT)}")


def validate(
    sql: str,
    role: RoleName | None,
    layer: SemanticLayer,
    policy: SqlPolicy | None = None,
) -> SqlValidationResult:
    """Allow exactly one safe SELECT that uses only what ``role`` may see."""
    policy = policy or get_sql_policy()
    try:
        allowed = _role_schema(layer, role) if role is not None else {}
        if not allowed:
            raise _Blocked(BlockReason.NO_DATA_ACCESS, f"role {role} has no business tables")
        if not sql or not sql.strip():
            raise _Blocked(BlockReason.EMPTY_SQL, "empty query")
        tree = _parse_single(sql)
        _check_statement_types(tree)
        _check_functions(tree, policy)
        tables = _check_tables(tree, allowed)
        qualified, columns = _qualify_columns(tree, allowed)
        final = _apply_limit(qualified, policy)
    except _Blocked as blocked:
        return SqlValidationResult(
            allowed=False,
            reason_code=blocked.reason,
            user_message=BLOCK_MESSAGES[blocked.reason],
            detail=blocked.detail,
            original_sql=sql,
        )
    return SqlValidationResult(
        allowed=True,
        tables=tables,
        columns=columns,
        original_sql=sql,
        # Regenerated from the parse tree without comments: only what was checked runs.
        final_sql=final.sql(dialect=DIALECT, comments=False),
    )
