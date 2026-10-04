import os

import pytest
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from app.core.config import Settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        database_url=None,
        postgres_password=SecretStr("test-only-password"),
        postgres_port=1,
        database_timeout_seconds=0.2,
    )


@pytest.fixture
def integration_url():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    url = make_url(value)
    if url.drivername != "postgresql+asyncpg" or not (url.database or "").endswith("_test"):
        pytest.fail("Integration tests require postgresql+asyncpg and a database ending in _test")
    return url
