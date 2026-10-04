"""Alembic environment. Reads DATABASE_URL from elums.config so there is
exactly one place the connection string comes from (not a second copy
pasted into alembic.ini)."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from elums.config import settings
from elums.models import Base  # noqa: F401 — populates Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """Procrastinate owns its own schema (`procrastinate schema --apply`,
    see elums/jobs/app.py) — those tables are never part of Base.metadata,
    so autogenerate sees them as "removed" and will happily generate DROP
    TABLE statements for the entire job queue. Hit directly Oct 3 2026
    (M6): a users/sessions migration came back wanting to drop
    procrastinate_jobs, procrastinate_events, procrastinate_workers, and
    procrastinate_periodic_defers. Caught before it was ever applied —
    excluded here so it can't happen again."""
    if type_ == "table" and name is not None and name.startswith("procrastinate_"):
        return False
    return True

# psycopg3 supports Alembic's sync migration runner directly through the
# same "+psycopg" dialect the app uses async — no second driver dependency.
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
