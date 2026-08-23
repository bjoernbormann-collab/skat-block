"""Alembic environment.

The database URL comes from app.config, never from alembic.ini, so `alembic
upgrade head` and the running app can never disagree about which database they
mean.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context) -> str | bool:
    """Render our custom column types as their plain storage types.

    Migration files must stay readable and self-contained years from now. If they
    imported app.models.base, an old migration would break the moment that module
    is refactored -- and the custom types are pure Python-side conversions anyway:
    what the database actually gets is a BIGINT or a TIMESTAMP.
    """
    from app.models.base import ExactDecimal, UtcDateTime

    if type_ == "type":
        if isinstance(obj, ExactDecimal):
            return "sa.BigInteger()"
        if isinstance(obj, UtcDateTime):
            return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_item=render_item,
        # SQLite cannot ALTER most things in place; batch mode rebuilds the table.
        render_as_batch=settings.is_sqlite,
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
            render_item=render_item,
            render_as_batch=settings.is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
