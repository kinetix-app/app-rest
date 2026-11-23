"""Typed environment configuration without import-time database connections."""

from math import ceil
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

_CONTAINER_NAME_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$"
_POSTGRES_DIALECT = "postgresql+psycopg"
_POSTGRES_URL_SCHEMES = {"postgres", "postgresql", _POSTGRES_DIALECT, "postgresql+asyncpg"}


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    database_url: SecretStr
    database_timeout_seconds: float = Field(default=2, gt=0, le=30)

    @model_validator(mode="after")
    def validate_database_configuration(self) -> Self:
        self.database_connection_url()
        return self

    def database_connection_url(self) -> URL:
        try:
            url = make_url(self.database_url.get_secret_value())
        except ArgumentError, ValueError:
            raise ValueError("DATABASE_URL must be a valid PostgreSQL connection string") from None
        if url.drivername not in _POSTGRES_URL_SCHEMES or not (url.host and url.database):
            raise ValueError("DATABASE_URL must specify a PostgreSQL host and database")
        # Older configurations may use the asyncpg spelling for the TLS mode.
        if (legacy_ssl_mode := url.query.get("ssl")) is not None:
            if "sslmode" in url.query:
                raise ValueError("DATABASE_URL must specify only one of sslmode and ssl")
            url = url.difference_update_query(["ssl"]).update_query_dict(
                {"sslmode": legacy_ssl_mode}
            )
        return url.set(drivername=_POSTGRES_DIALECT)

    def database_connect_args(self) -> dict[str, int]:
        # libpq accepts a whole number of seconds.
        return {"connect_timeout": ceil(self.database_timeout_seconds)}


class Settings(DatabaseSettings):
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8081"])
    auth_mode: Literal["basic", "clerk"] | None = None
    basic_auth_users: dict[str, SecretStr] = Field(default_factory=dict)

    azure_storage_connection_string: SecretStr | None = None
    azure_storage_container: str = Field(default="exercises", pattern=_CONTAINER_NAME_PATTERN)
    azure_storage_profile_container: str = Field(
        default="profile-pictures", pattern=_CONTAINER_NAME_PATTERN
    )
    azure_storage_post_container: str = Field(default="post-media", pattern=_CONTAINER_NAME_PATTERN)
    azure_storage_media_base_url: str | None = None
    azure_storage_local_public_read: bool = False
    azure_storage_timeout_seconds: float = Field(default=30, gt=0, le=120)

    clerk_issuer: str | None = None
    clerk_secret_key: SecretStr | None = None
    clerk_authorized_parties: list[str] = Field(default_factory=list)
    clerk_audience: str | None = None
    clerk_clock_skew_seconds: int = Field(default=5, ge=0, le=30)

    @field_validator(
        "auth_mode",
        "clerk_issuer",
        "clerk_audience",
        "clerk_secret_key",
        "azure_storage_connection_string",
        "azure_storage_media_base_url",
        mode="before",
    )
    @classmethod
    def empty_auth_setting(cls, value: str | None) -> str | None:
        return None if value == "" else value

    @field_validator("basic_auth_users")
    @classmethod
    def validate_development_users(cls, users: dict[str, SecretStr]) -> dict[str, SecretStr]:
        if any(
            not username
            or len(username) > 255
            or ":" in username
            or not password.get_secret_value()
            for username, password in users.items()
        ):
            raise ValueError("Development users require usernames and nonempty passwords")
        return users

    @model_validator(mode="after")
    def validate_authentication_configuration(self) -> Self:
        if self.auth_mode is None:
            self.auth_mode = "clerk" if self.app_env == "production" else "basic"
        if self.auth_mode == "basic" and self.app_env == "production":
            raise ValueError("AUTH_MODE=basic is forbidden in production")
        if self.clerk_issuer is not None:
            url = urlsplit(self.clerk_issuer)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in ("", "/")
                or len(self.clerk_issuer) > 512
            ):
                raise ValueError("CLERK_ISSUER must be an HTTPS origin without credentials")
            self.clerk_issuer = self.clerk_issuer.rstrip("/")
        if self.app_env == "production" and not self.clerk_issuer:
            raise ValueError("CLERK_ISSUER is required in production")
        if self.app_env == "production" and not self.clerk_secret_key:
            raise ValueError("CLERK_SECRET_KEY is required in production")
        return self

    @model_validator(mode="after")
    def validate_storage_configuration(self) -> Self:
        if bool(self.azure_storage_connection_string) != bool(self.azure_storage_media_base_url):
            raise ValueError("Azure storage requires a connection string and media base URL")
        containers = (
            self.azure_storage_container,
            self.azure_storage_profile_container,
            self.azure_storage_post_container,
        )
        if self.azure_storage_profile_container == self.azure_storage_container:
            raise ValueError("Profile and exercise containers must be different")
        if len(set(containers)) != len(containers):
            raise ValueError("Exercise, profile and post containers must be different")
        if any("--" in name for name in containers):
            raise ValueError("Azure container names cannot contain consecutive hyphens")
        if value := self.azure_storage_media_base_url:
            url = urlsplit(value)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError(
                    "Azure storage URLs must be HTTP(S) without credentials or queries"
                )
            if self.app_env == "production" and url.scheme != "https":
                raise ValueError("Production Azure storage URLs require HTTPS")
        if self.azure_storage_local_public_read and self.app_env == "production":
            raise ValueError("Local public blob access is forbidden in production")
        return self
