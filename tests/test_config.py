import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def test_missing_credentials_fail_without_exposing_input(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(ValidationError, match="Set POSTGRES_PASSWORD or DATABASE_URL"):
        Settings(_env_file=None)


def test_password_characters_are_preserved_in_connection_url():
    password = "local@password:/?#%"
    settings = Settings(
        _env_file=None, database_url=None, postgres_password=SecretStr(password), postgres_port=5432
    )
    url = settings.database_connection_url()
    assert url.password == password
    assert password not in repr(settings)
    assert password not in str(url)


@pytest.mark.parametrize("value", ["not-a-url", "sqlite:///local.db", "postgresql://user@db/name"])
def test_invalid_database_url_is_rejected_and_hidden(value):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url=SecretStr(value))
    assert value not in str(error.value)


@pytest.mark.parametrize("value", [0, -1, 31])
def test_readiness_timeout_is_bounded(value):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, postgres_password=SecretStr("test"), database_timeout_seconds=value
        )
