"""Typed environment configuration without import-time database connections."""

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr | None = None
    postgres_user: str = Field(default="fitness", min_length=1)
    postgres_password: SecretStr | None = None
    postgres_db: str = Field(default="fitness", min_length=1)
    postgres_host: str = Field(default="127.0.0.1", min_length=1)
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    database_timeout_seconds: float = Field(default=2, gt=0, le=30)
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8081"])
    auth_mode: Literal["basic", "clerk"] | None = None
    basic_auth_users: dict[str, SecretStr] = Field(default_factory=dict)

    azure_storage_account_name: str | None = Field(default=None, pattern=r"^[a-z0-9]{3,24}$")
    azure_storage_account_url: str | None = None
    azure_storage_account_key: SecretStr | None = None
    azure_storage_container: str = Field(
        default="exercises", pattern=r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$"
    )
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
        "database_url",
        "clerk_issuer",
        "clerk_audience",
        "clerk_secret_key",
        "azure_storage_account_name",
        "azure_storage_account_url",
        "azure_storage_account_key",
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
    def validate_database_configuration(self) -> Self:
        if self.database_url is not None:
            try:
                url = make_url(self.database_url.get_secret_value())
            except ArgumentError:
                raise ValueError("DATABASE_URL must be a valid PostgreSQL connection URL") from None
            if url.drivername != "postgresql+asyncpg" or not url.host or not url.database:
                raise ValueError("DATABASE_URL must use postgresql+asyncpg with host and database")
        elif self.postgres_password is None or not self.postgres_password.get_secret_value():
            raise ValueError(
                "Set POSTGRES_PASSWORD or DATABASE_URL before starting the application"
            )
        return self

    @model_validator(mode="after")
    def validate_storage_configuration(self) -> Self:
        values = (
            self.azure_storage_account_name,
            self.azure_storage_account_url,
            self.azure_storage_account_key,
            self.azure_storage_media_base_url,
        )
        if any(values) and not all(values):
            raise ValueError(
                "Azure storage requires account name, account URL, key and media base URL"
            )
        if "--" in self.azure_storage_container:
            raise ValueError("Azure container names cannot contain consecutive hyphens")
        for value in (self.azure_storage_account_url, self.azure_storage_media_base_url):
            if value is None:
                continue
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

    def database_connection_url(self) -> URL:
        if self.database_url is not None:
            return make_url(self.database_url.get_secret_value())
        assert self.postgres_password is not None
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
