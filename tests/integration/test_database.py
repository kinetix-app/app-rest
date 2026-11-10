from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.mark.anyio
async def test_readiness_queries_postgresql(integration_url):
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=SecretStr(integration_url.render_as_string(hide_password=False)),
    )
    app = create_app(settings)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_committed_data_survives_engine_restart_and_rollback(integration_url):
    # Test-owned table; this is infrastructure evidence, not a product entity.
    table = "foundation_" + uuid4().hex
    engine = create_async_engine(integration_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"CREATE TABLE {table} (value INTEGER NOT NULL)"))
            await connection.execute(text(f"INSERT INTO {table} VALUES (7)"))
        await engine.dispose()
        async with engine.connect() as connection:
            assert await connection.scalar(text(f"SELECT value FROM {table}")) == 7
            await connection.execute(text(f"INSERT INTO {table} VALUES (99)"))
            await connection.rollback()
        async with engine.connect() as connection:
            assert await connection.scalar(text(f"SELECT count(*) FROM {table}")) == 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
        await engine.dispose()


def test_alembic_bootstrap_and_metadata_consistency(integration_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", integration_url.render_as_string(hide_password=False))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.anyio
async def test_routine_cover_upgrade_preserves_existing_templates(integration_url):
    schema = "routine_upgrade_" + uuid4().hex
    engine = create_async_engine(integration_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))

            def migrate(conn, revision):
                config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
                config.attributes["connection"] = conn
                command.upgrade(config, revision)

            await connection.run_sync(migrate, "20261102_01")
            await connection.execute(
                text(
                    "INSERT INTO routine (name, description) "
                    "VALUES ('Legacy routine', 'Preserved note')"
                )
            )
            await connection.run_sync(migrate, "head")
            result = (
                await connection.execute(
                    text("SELECT name, description, picture_blob_name FROM routine")
                )
            ).one()
            assert tuple(result) == ("Legacy routine", "Preserved note", None)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


@pytest.mark.anyio
async def test_routine_soft_delete_upgrade_preserves_covers_and_completed_history(integration_url):
    schema = "routine_retire_" + uuid4().hex
    engine = create_async_engine(integration_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))

            def migrate(conn, revision):
                config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
                config.attributes["connection"] = conn
                command.upgrade(config, revision)

            await connection.run_sync(migrate, "20261103_01")
            user_id = await connection.scalar(text("INSERT INTO users DEFAULT VALUES RETURNING id"))
            routine_id = await connection.scalar(
                text(
                    "INSERT INTO routine (user_id, name, description, picture_blob_name) "
                    "VALUES (:user_id, 'Legacy routine', 'Preserved note', "
                    "'private-cover.jpg') RETURNING id"
                ),
                {"user_id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO training_session "
                    "(user_id, routine_id, activity_type, started_at, ended_at) "
                    "VALUES (:user_id, :routine_id, 'gym', "
                    "'2026-11-01T10:00:00Z', '2026-11-01T11:00:00Z')"
                ),
                {"user_id": user_id, "routine_id": routine_id},
            )
            await connection.run_sync(migrate, "head")
            row = (
                await connection.execute(
                    text("SELECT id, name, description, picture_blob_name, deleted_at FROM routine")
                )
            ).one()
            assert tuple(row) == (
                routine_id,
                "Legacy routine",
                "Preserved note",
                "private-cover.jpg",
                None,
            )
            assert (
                await connection.scalar(text("SELECT routine_id FROM training_session"))
                == routine_id
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
