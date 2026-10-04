"""Typed environment configuration without import-time database connections."""

from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
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
