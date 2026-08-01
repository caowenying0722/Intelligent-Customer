from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from utils.env_loader import clean_env_value

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    application_env: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("APPLICATION_ENV", "APP_ENV"),
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    model_provider: Literal["openai", "anthropic"] | None = Field(
        default=None,
        validation_alias=AliasChoices("MODEL_PROVIDER", "LLM__PROVIDER"),
    )
    model_request_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    model_max_retries: int = Field(default=2, ge=0, le=5)
    model_max_concurrency: int = Field(default=8, ge=1, le=100)
    model_failure_threshold: int = Field(default=5, ge=1, le=100)
    model_cooldown_seconds: float = Field(default=30.0, gt=0, le=3600)
    model_rate_limit_per_second: int | None = Field(default=None, ge=1, le=10000)
    model_health_token: SecretStr | None = None
    metrics_token: SecretStr | None = None
    model_cache_max_entries: int = Field(default=1024, ge=1, le=100_000)
    model_cache_ttl_seconds: float = Field(default=60.0, gt=0, le=86_400)
    model_cache_max_entries_per_tenant: int | None = Field(
        default=None, ge=1, le=100_000
    )
    model_cache_namespace: str = Field(
        default="model-cache", min_length=1, max_length=64
    )
    model_quota_max_calls: int | None = Field(default=None, ge=1, le=1_000_000)
    model_quota_window_seconds: float = Field(default=60.0, gt=0, le=86_400)
    model_ca_bundle: Path | None = None
    agent_max_steps: int = Field(default=10, ge=1, le=50)
    agent_max_tool_calls: int = Field(default=5, ge=1, le=20)
    agent_max_input_chars: int = Field(default=4000, ge=1, le=100_000)
    agent_max_context_chars: int = Field(default=32_000, ge=1, le=1_000_000)
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8501"]
    )
    api_host: str = Field(default="127.0.0.1", min_length=1)
    api_port: int = Field(default=8000, ge=1, le=65535)
    trace_max_spans: int = Field(default=1024, ge=1, le=100_000)
    database_url: str | None = Field(
        default=None, validation_alias=AliasChoices("DATABASE_URL")
    )
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    database_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    database_isolation_level: Literal[
        "READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"
    ] = "READ COMMITTED"

    openai_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None
    moonshot_api_key: SecretStr | None = None
    anthropic_auth_token: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str | None = None
    anthropic_default_sonnet_model: str | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("anthropic_base_url", mode="before")
    @classmethod
    def normalize_anthropic_base_url(cls, value: object) -> object:
        return clean_env_value(value) if isinstance(value, str) else value

    @field_validator("model_ca_bundle", mode="before")
    @classmethod
    def resolve_ca_bundle(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        path = Path(str(value).strip()).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        resolved = path.resolve()
        if not resolved.is_file():
            raise ValueError(
                f"MODEL_CA_BUNDLE must point to an existing file: {resolved}"
            )
        return resolved

    @field_validator("allowed_origins")
    @classmethod
    def validate_allowed_origins(cls, value: list[str]) -> list[str]:
        normalized = [origin.strip().rstrip("/") for origin in value if origin.strip()]
        if not normalized:
            raise ValueError("ALLOWED_ORIGINS must contain at least one origin")
        for origin in normalized:
            if origin != "*" and not origin.startswith(("http://", "https://")):
                raise ValueError(f"Invalid allowed origin: {origin}")
        return list(dict.fromkeys(normalized))

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        parsed = urlparse(str(value).strip())
        if parsed.scheme not in {"postgresql", "postgresql+psycopg", "sqlite"}:
            raise ValueError(
                "DATABASE_URL must use postgresql, postgresql+psycopg, or sqlite"
            )
        return str(value).strip()

    @model_validator(mode="after")
    def reject_production_wildcard_origin(self) -> Settings:
        if self.application_env == "production" and "*" in self.allowed_origins:
            raise ValueError("Wildcard ALLOWED_ORIGINS is forbidden in production")
        return self

    @property
    def resolved_model_provider(self) -> Literal["openai", "anthropic"]:
        if self.model_provider is not None:
            return self.model_provider
        if self.anthropic_auth_token is not None or self.anthropic_api_key is not None:
            return "anthropic"
        return "openai"

    @property
    def anthropic_api_key_value(self) -> str | None:
        secret = self.anthropic_auth_token or self.anthropic_api_key
        return secret.get_secret_value() if secret is not None else None

    @property
    def openai_compatible_api_key_value(self) -> str | None:
        secret = self.openai_api_key or self.deepseek_api_key or self.moonshot_api_key
        return secret.get_secret_value() if secret is not None else None

    @property
    def model_health_token_value(self) -> str | None:
        return (
            self.model_health_token.get_secret_value()
            if self.model_health_token
            else None
        )

    @property
    def metrics_token_value(self) -> str | None:
        return self.metrics_token.get_secret_value() if self.metrics_token else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
