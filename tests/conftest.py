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


@pytest.fixture(scope="session")
def signing_material():
    import json

    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.algorithms import RSAAlgorithm

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update(kid="test-key", alg="RS256", use="sig")
    return private_key, jwk


@pytest.fixture
def signed_token(signing_material):
    import time

    import jwt

    def create(issuer="https://kinetix-test.clerk.accounts.dev", **overrides):
        now = int(time.time())
        claims = {
            "iss": issuer,
            "sub": "user_alice",
            "sid": "sess_alice",
            "exp": now + 60,
            "nbf": now - 5,
            "iat": now - 5,
        }
        claims.update(overrides)
        claims = {key: value for key, value in claims.items() if value is not None}
        return jwt.encode(
            claims, signing_material[0], algorithm="RS256", headers={"kid": "test-key"}
        )

    return create


@pytest.fixture
def clerk_jwks(monkeypatch, signing_material):
    """Exercise the real SDK verifier with an isolated cache and mocked HTTP transport."""
    from importlib import import_module
    from types import SimpleNamespace

    import httpx
    from clerk_backend_api.security.cache import Cache

    sdk = import_module("clerk_backend_api.security.verifytoken")
    requests = []
    remote = SimpleNamespace(
        response=httpx.Response(200, json={"keys": [signing_material[1]]}), error=None
    )

    def handle(request):
        requests.append(request)
        if remote.error is not None:
            raise remote.error
        return remote.response

    client_class = httpx.AsyncClient
    monkeypatch.setattr(sdk, "__jwkcache", Cache())
    monkeypatch.setattr(
        sdk,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda **kwargs: client_class(transport=httpx.MockTransport(handle)),
            AsyncHTTPTransport=httpx.AsyncHTTPTransport,
            TimeoutException=httpx.TimeoutException,
        ),
    )
    remote.requests = requests
    return remote
