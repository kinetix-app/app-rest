"""Alembic environment sharing the application's typed connection settings."""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db.base import Base

# Import implemented feature models here so autogenerate sees their tables.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=Settings().database_connection_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    settings = Settings()
    engine = create_async_engine(
        settings.database_connection_url(),
        poolclass=pool.NullPool,
        connect_args={"timeout": settings.database_timeout_seconds},
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
