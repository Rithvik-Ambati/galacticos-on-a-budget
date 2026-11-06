from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from config.settings import get_settings
from db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# A hung network path to the DB (bad internal hostname, dropped connection)
# otherwise blocks forever with zero output, since neither asyncio nor
# asyncpg apply a connect timeout by default -- that turns into a silently
# stuck container, and on Render a Deploying... that never finishes or
# fails. Fail fast and loudly instead.
CONNECT_TIMEOUT_SECONDS = 15
OVERALL_TIMEOUT_SECONDS = 90


def get_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connect_args = {"timeout": CONNECT_TIMEOUT_SECONDS} if get_url().startswith("postgresql") else {}
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(asyncio.wait_for(run_migrations_online(), timeout=OVERALL_TIMEOUT_SECONDS))
