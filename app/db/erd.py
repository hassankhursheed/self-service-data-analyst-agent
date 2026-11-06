"""Render the application models as a Mermaid ``erDiagram`` (kept in the design docs)."""

from sqlalchemy import Column, Table, UniqueConstraint
from sqlalchemy.dialects import postgresql

from app.db.models import Base


def _type_name(column: Column[object]) -> str:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    name = column.type.compile(dialect=dialect).lower()
    name = name.split("(")[0].replace(" with time zone", "tz").replace(" ", "_")
    return name.replace("[]", "_array")


def _unique_columns(table: Table) -> set[str]:
    return {
        constraint.columns[0].name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint) and len(constraint.columns) == 1
    }


def _keys(column: Column[object], unique: set[str]) -> str:
    keys = []
    if column.primary_key:
        keys.append("PK")
    if column.foreign_keys:
        keys.append("FK")
    if column.name in unique and not column.primary_key:
        keys.append("UK")
    return ", ".join(keys)


def render_erd() -> str:
    """Return the Mermaid source: relationships first, then every table's columns."""
    tables = sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
    lines = ["erDiagram"]
    for table in tables:
        for fk in sorted(table.foreign_keys, key=lambda f: f.parent.name):
            parent = fk.column.table.name
            many = "o{"
            one = "|o" if fk.parent.nullable else "||"
            lines.append(f'    {parent} {one}--{many} {table.name} : "{fk.parent.name}"')
    for table in tables:
        unique = _unique_columns(table)
        lines.append(f"    {table.name} {{")
        for column in table.columns:
            keys = _keys(column, unique)
            lines.append(f"        {_type_name(column)} {column.name}{' ' + keys if keys else ''}")
        lines.append("    }")
    return "\n".join(lines) + "\n"
