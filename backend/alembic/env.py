"""Alembic environment.

`alembic upgrade head` imports THIS file. It:
  1. reads DATABASE_URL (via app.config, so .env works),
  2. points Alembic at Base.metadata (the single source of truth for tables),
  3. runs the migrations against the real database.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base

# Importing the models module is what REGISTERS the tables on Base.metadata.
# Without this import, autogenerate would think the database should be empty.
import app.models  # noqa: F401  # isort: skip

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `%` must be escaped for ConfigParser, so passwords containing % work.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it (useful for DBAs/review)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite cannot ALTER most columns; batch mode rewrites the table.
            # Only relevant for local SQLite smoke tests.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
