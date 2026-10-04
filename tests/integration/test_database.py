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
