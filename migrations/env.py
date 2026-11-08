"""Alembic environment: migrations touch the ``app`` schema only, never Northwind."""

from alembic import context
from sqlalchemy import URL, create_engine, text

from app.core.config import get_settings
from app.db.models import APP_SCHEMA, Base

target_metadata = Base.metadata


def _owner_url() -> URL:
    """The owner URL, or the one a caller passed in ``config.attributes["url"]``
    (the migration test uses a scratch database)."""
    override = context.config.attributes.get("url")
    if isinstance(override, URL):
        return override
    return get_settings().owner_sqlalchemy_url()


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Only reflect and compare the app schema, so autogenerate never sees Northwind."""
    if type_ == "schema":
        return name == APP_SCHEMA
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_owner_url().render_as_string(hide_password=True),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
        version_table_schema=APP_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_owner_url())
    with engine.connect() as connection:
        # The schema must exist before Alembic creates its version table in it.
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{APP_SCHEMA}"'))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            version_table_schema=APP_SCHEMA,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
