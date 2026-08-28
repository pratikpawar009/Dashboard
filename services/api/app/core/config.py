from typing import Annotated, Any

from fastapi import Request
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Dev-bypass gating (D-01) is fail-closed: allow-list membership, never a
# `!= "production"` deny-check. A deny-check silently admits any unanticipated
# value (abbreviation, typo, an unnamed real environment like "staging"); an
# allow-list denies by default, so only these exact values ever unlock it.
NON_PRODUCTION_ENVIRONMENTS: frozenset[str] = frozenset(
    {"local", "development", "dev", "test", "ci"}
)


class Settings(BaseSettings):
    """Runtime configuration, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "dashboard-api"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/dashboard"
    log_level: str = "INFO"

    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_issuer: str | None = None
    oidc_realm: str | None = None
    # D-11: explicit override for the OAuth `redirect_uri` sent to Keycloak.
    # Optional — falls back to a request-derived callback URL when unset (see
    # `app/auth/oidc.py::_resolve_redirect_uri`). Deliberately NOT part of
    # `oidc_configured`'s completeness triple below.
    oidc_redirect_uri: str | None = None
    oidc_scope: str = "openid profile email groups"
    program_group_prefix: str = "program-"
    # Accepts a single origin (CORS_ORIGINS=https://dashboard.example.com) or a
    # comma-separated list (CORS_ORIGINS=https://a.example.com,https://b.example.com).
    # `NoDecode` opts this field out of pydantic-settings' default JSON-decode-from-env
    # behavior (which would raise on a bare, non-JSON origin string); the validator
    # below does the actual split.
    cors_origins: Annotated[list[str], NoDecode] = []

    @field_validator("environment", mode="after")
    @classmethod
    def _normalize_environment(cls, value: str) -> str:
        """Lowercase once at load so every call site compares against a normalized value."""
        return value.lower()

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def dev_bypass_enabled(self) -> bool:
        """True only for allow-listed non-production environments (D-01, fail-closed)."""
        return self.environment in NON_PRODUCTION_ENVIRONMENTS

    @property
    def oidc_configured(self) -> bool:
        """True only when client_id, secret, and issuer are all present and non-empty."""
        return (
            bool(self.oidc_client_id) and bool(self.oidc_client_secret) and bool(self.oidc_issuer)
        )


settings = Settings()


def get_settings(request: Request) -> Settings:
    """FastAPI dependency returning the effective per-app Settings (D-07).

    Route handlers must read config via `Depends(get_settings)`, never by
    importing the module-level `settings` singleton directly, so a test's
    per-app settings override (`app.state.settings`) is honored.
    """
    return request.app.state.settings
