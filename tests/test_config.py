from urllib.parse import quote

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def test_missing_credentials_fail_without_exposing_input(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_password_characters_are_preserved_in_connection_url():
    password = "local@password:/?#%"
    settings = Settings(
        _env_file=None,
        database_url=f"postgresql://user:{quote(password, safe='')}@db/name?sslmode=require",
    )
    url = settings.database_connection_url()
    assert url.password == password
    assert url.drivername == "postgresql+asyncpg"
    assert url.query == {"ssl": "require"}
    assert password not in repr(settings)
    assert password not in str(url)


@pytest.mark.parametrize("value", ["not-a-url", "sqlite:///local.db", "postgresql://user@/name"])
def test_invalid_database_url_is_rejected_and_hidden(value):
    database_url = SecretStr(value)
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url=database_url)
    assert value not in str(error.value)


@pytest.mark.parametrize("value", [0, -1, 31])
def test_readiness_timeout_is_bounded(value):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql://user:test@db/name",
            database_timeout_seconds=value,
        )


@pytest.mark.parametrize(
    "issuer",
    [
        "http://auth.example",
        "https://user:pass@auth.example",
        "https://auth.example/path",
        "https://auth.example?key=secret",
    ],
)
def test_invalid_clerk_issuer_rejected(issuer):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="postgresql://user:test@db/name", clerk_issuer=issuer)


def test_production_requires_authentication_configuration():
    with pytest.raises(ValidationError, match="CLERK_ISSUER is required"):
        Settings(
            _env_file=None, database_url="postgresql://user:test@db/name", app_env="production"
        )


@pytest.mark.parametrize("value", [None, ""])
def test_production_requires_clerk_secret_key(value):
    settings_values = {
        "_env_file": None,
        "database_url": "postgresql://user:test@db/name",
        "app_env": "production",
        "clerk_issuer": "https://kinetix-test.clerk.accounts.dev",
        "clerk_secret_key": value,
    }
    with pytest.raises(ValidationError, match="CLERK_SECRET_KEY is required"):
        Settings(**settings_values)


def test_clerk_secret_is_hidden():
    secret = "sk_test_backend_only"
    settings = Settings(
        _env_file=None, database_url="postgresql://user:test@db/name", clerk_secret_key=secret
    )
    assert secret not in repr(settings)
    assert settings.clerk_secret_key.get_secret_value() == secret
