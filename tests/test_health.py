import logging

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.main import create_app


@pytest.mark.anyio
async def test_liveness_remains_available_when_database_is_down(settings):
    app = create_app(settings)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            live = await client.get("/health/live")
            ready = await client.get("/health/ready")
            live_after = await client.get("/health/live")
    assert live.status_code == live_after.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable"}
    assert "test-only-password" not in ready.text


@pytest.mark.anyio
async def test_request_logs_do_not_include_query_credentials(settings, caplog):
    app = create_app(settings)
    with caplog.at_level(logging.INFO, logger="kinetix.requests"):
        async with LifespanManager(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/health/live?token=private-example-token")
    records = [
        record.getMessage() for record in caplog.records if record.name == "kinetix.requests"
    ]
    assert records and all("private-example-token" not in record for record in records)
    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.anyio
async def test_lifespan_disposes_the_engine(settings, monkeypatch):
    app = create_app(settings)
    disposed = []
    original_dispose = AsyncEngine.dispose

    async def dispose(engine, close=True):
        disposed.append(engine)
        await original_dispose(engine, close=close)

    monkeypatch.setattr(AsyncEngine, "dispose", dispose)
    async with LifespanManager(app):
        engine = app.state.engine
    assert disposed == [engine]
