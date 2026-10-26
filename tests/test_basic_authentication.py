from base64 import b64encode
from typing import Annotated

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import Depends
from pydantic import SecretStr, ValidationError

from app.core.auth.basic import verify_basic
from app.core.auth.dependencies import get_verified_identity
from app.core.auth.types import InvalidCredentials, VerifiedIdentity
from app.core.config import Settings
from app.main import create_app


def authorization(username="alice@example.test", password="local-test-only"):
    encoded = b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


@pytest.fixture
def basic_settings(settings):
    return Settings(
        _env_file=None,
        postgres_password=settings.postgres_password,
        auth_mode="basic",
        basic_auth_users={
            "alice@example.test": SecretStr("local-test-only"),
            "bob@example.test": SecretStr("another-test-only"),
        },
    )


def test_configured_users_have_distinct_development_identities(basic_settings):
    alice = verify_basic(authorization(), basic_settings)
    bob = verify_basic(authorization("bob@example.test", "another-test-only"), basic_settings)
    assert alice == VerifiedIdentity("urn:kinetix:dev", "alice@example.test", None)
    assert bob.subject != alice.subject
    assert "local-test-only" not in repr(basic_settings)


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer token",
        "Basic not-base64",
        "Basic YWxpY2U=",
        authorization(password="wrong"),
        authorization(username="unknown@example.test"),
    ],
)
def test_invalid_credentials_are_rejected(basic_settings, header):
    with pytest.raises(InvalidCredentials):
        verify_basic(header, basic_settings)


def test_clerk_mode_never_uses_configured_development_credentials(basic_settings):
    basic_settings.auth_mode = "clerk"
    header = authorization()
    with pytest.raises(InvalidCredentials):
        verify_basic(header, basic_settings)


def test_production_rejects_basic_even_if_settings_are_mutated(basic_settings):
    basic_settings.app_env = "production"
    header = authorization()
    with pytest.raises(InvalidCredentials):
        verify_basic(header, basic_settings)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"app_env": "production", "basic_auth_users": {"alice": "secret"}}, "forbidden"),
        ({"basic_auth_users": {"alice": ""}}, "nonempty passwords"),
    ],
)
def test_invalid_basic_configuration_fails_at_startup(overrides, message):
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, postgres_password="test-only", auth_mode="basic", **overrides)


@pytest.mark.anyio
async def test_basic_dependency_returns_identity_and_denies_wrong_scheme(basic_settings):
    app = create_app(basic_settings)

    @app.get("/test-identity")
    async def identity(value: Annotated[VerifiedIdentity, Depends(get_verified_identity)]):
        return {"issuer": value.issuer, "subject": value.subject, "session_id": value.session_id}

    async with LifespanManager(app):
        assert app.openapi()["components"]["securitySchemes"]["Authentication"]["scheme"] == "basic"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/me", headers={"Origin": "http://localhost:8081"})
            assert response.status_code == 401
            assert response.json() == {"detail": "Invalid development credentials"}
            assert response.headers["WWW-Authenticate"] == "Basic"
            assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:8081"
            assert response.headers["Access-Control-Expose-Headers"] == "WWW-Authenticate"

            response = await client.get(
                "/test-identity", headers={"Authorization": authorization()}
            )
            assert response.status_code == 200
            assert response.json() == {
                "issuer": "urn:kinetix:dev",
                "subject": "alice@example.test",
                "session_id": None,
            }
            response = await client.get("/api/v1/me", headers={"Authorization": "Bearer token"})
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Basic"
            app.state.settings.auth_mode = "clerk"
            response = await client.get("/api/v1/me", headers={"Authorization": authorization()})
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_auth_mode_defaults_follow_environment(environment):
    settings = Settings(
        _env_file=None,
        postgres_password="test-only",
        app_env=environment,
        clerk_issuer="https://kinetix-test.clerk.accounts.dev",
        clerk_secret_key="sk_test_backend_only",
    )
    assert settings.auth_mode == ("clerk" if environment == "production" else "basic")


def test_unconfigured_basic_mode_accepts_no_accounts():
    settings = Settings(_env_file=None, postgres_password="test-only")
    header = authorization()
    with pytest.raises(InvalidCredentials):
        verify_basic(header, settings)


def test_empty_mode_and_database_url_use_defaults():
    settings = Settings(
        _env_file=None, postgres_password="test-only", auth_mode="", database_url=""
    )
    assert settings.auth_mode == "basic"
    assert settings.database_connection_url().host == "127.0.0.1"
