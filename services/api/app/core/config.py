import json
import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import Request
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

# Dev-bypass gating (D-01) is fail-closed: allow-list membership, never a
# `!= "production"` deny-check. A deny-check silently admits any unanticipated
# value (abbreviation, typo, an unnamed real environment like "staging"); an
# allow-list denies by default, so only these exact values ever unlock it.
NON_PRODUCTION_ENVIRONMENTS: frozenset[str] = frozenset(
    {"local", "development", "dev", "test", "ci"}
)

# AUTH-02-FR-1 / D-01: PERSONA_ROLE_MAP is not itself a secret, but
# .claude/rules/security-baseline.md and AUTH-01's
# tests/unit/test_auth_logging_security.py establish that raw config values
# are never logged verbatim. Same bounded-excerpt idiom as
# app/dependencies/range.py's `_capped_rejected_value`: a fixed-length
# excerpt with an explicit truncation marker keeps a genuine parse-error
# typo legible while bounding a hostile/oversized value to a small, fixed
# cost per log line.
_MAX_LOGGED_PERSONA_ROLE_MAP_LEN = 64


def _masked_excerpt(value: str) -> str:
    if len(value) <= _MAX_LOGGED_PERSONA_ROLE_MAP_LEN:
        return value
    return f"{value[:_MAX_LOGGED_PERSONA_ROLE_MAP_LEN]}...<truncated>"


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

    # AUTH-02-FR-1 / D-01: Tier-1 override for PersonaResolver, parsed from a
    # JSON-dict env var. `NoDecode` opts this out of pydantic-settings'
    # default JSON-decode-from-env behavior (would raise on invalid JSON
    # before the validator below ever ran, defeating fail-open parsing);
    # the validator below does the actual `json.loads()` and is fail-open
    # on any parse error (see D-01).
    persona_role_map: Annotated[dict[str, str] | None, NoDecode] = None
    # D-05: Tier-2 YAML path override -- unused by default. `PersonaResolver`
    # computes its own `__file__`-anchored default path; this field exists
    # only so a future caller can override it explicitly. Deliberately NOT
    # given a `services/api/`-prefixed literal default (see D-05).
    persona_config_file: Path | None = None

    @field_validator("environment", mode="after")
    @classmethod
    def _normalize_environment(cls, value: str) -> str:
        """Lowercase once at load so every call site compares against a normalized value."""
        return value.lower()

    @field_validator("log_level", mode="after")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        """Uppercase once at load, mirroring `_normalize_environment`.

        `logging.Logger.setLevel` accepts only the exact upper-case names, so
        a lower-case `LOG_LEVEL=info` in `.env` -- an entirely reasonable
        thing to write, and what every log line itself prints -- raised
        `ValueError: Unknown level: 'info'` inside `configure_logging()`.
        That call runs at `app.main` import time, so the failure was a hard
        startup crash with a traceback pointing at the logging module rather
        than at the offending config value. Normalizing here keeps the
        case-insensitivity rule for env-sourced values in one place, next to
        `environment`'s, instead of pushing a `.upper()` onto every consumer.
        """
        return value.upper()

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("persona_role_map", mode="before")
    @classmethod
    def _parse_persona_role_map(cls, value: Any) -> Any:
        """Fail-open JSON parse (AUTH-02-FR-1 / D-01).

        Any parse failure -- invalid JSON, valid JSON that isn't an object,
        or an object whose values aren't all strings -- logs a warning and
        resolves the field to `None` (Tier-1 is then treated as empty; the
        resolver falls through to Tier-2/3). Never raises: this is
        deliberately fail-open at parse time, distinct from the fail-closed
        unmapped-role case the resolver itself enforces later (AC-4).
        """
        if value is None:
            return None
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                logger.warning(
                    "persona_role_map_parse_error",
                    extra={"raw_value": _masked_excerpt(value)},
                )
                return None
        else:
            parsed = value
        if not isinstance(parsed, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()
        ):
            logger.warning(
                "persona_role_map_parse_error",
                extra={"raw_value": _masked_excerpt(str(value))},
            )
            return None
        return parsed

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
