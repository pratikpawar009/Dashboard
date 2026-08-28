"""Unit tests for app/core/config.py's Settings schema — AUTH-01-TC-12 (FR-1).

Pure-unit: no DB, no network, no app boot. Every test constructs `Settings`
directly and reads its fields/properties.

Hermeticity (mandatory — Settings reads both the real process environment
and `services/api/.env` via `SettingsConfigDict(env_file=".env")`):

- `_clean_settings_env` (autouse) strips every env var this file cares about
  via `monkeypatch.delenv(..., raising=False)`, so an ambient `OIDC_*` /
  `ENVIRONMENT` / `CORS_ORIGINS` value set in the shell can never leak in.
- `_build_settings()` always builds via `_HermeticSettings` (`env_file=None`),
  neutralising a stray `services/api/.env` on disk — the two layers are
  independent (a developer's shell exports and a developer's `.env` file are
  separate leak vectors) and both must be closed. See `_HermeticSettings`'s
  own docstring for why this is a subclass override rather than the simpler
  `Settings(_env_file=None)` call.
- Verified by hand for this task: temporarily created `services/api/.env`
  with conflicting `ENVIRONMENT`/`OIDC_*`/`CORS_ORIGINS` values, re-ran this
  file (`pytest tests/unit/test_auth_config.py -v`) and confirmed every test
  still passed unchanged, then deleted that `.env` — it is gitignored and
  was never committed.

D-01 fail-closed semantics (allow-list, not a `!= "production"` deny-check)
are asserted here only at the `Settings.dev_bypass_enabled` property level.
The route-level 404 gating (AUTH-01-TC-08/09/22/23/37/38/39) belongs to the
`app/auth/dev_bypass.py` route tests, not this file.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_settings import SettingsConfigDict

from app.core.config import NON_PRODUCTION_ENVIRONMENTS, Settings


class _HermeticSettings(Settings):
    """Test-only subclass: disables `.env` loading (`env_file=None`).

    Passing `_env_file=None` straight to `Settings(...)` is the documented
    pydantic-settings mechanism for this, but pydantic's `BaseModel`
    metaclass is `@dataclass_transform`-decorated (PEP 681): mypy synthesizes
    every subclass's `__init__` from its declared fields alone, so private
    `BaseSettings` init kwargs like `_env_file` type-check on `BaseSettings`
    itself but not on a concrete subclass such as `Settings` — a known
    pydantic-settings/mypy limitation, not a real bug. Overriding
    `model_config` on a subclass instead reaches the same runtime effect
    through an ordinary, fully-typed class attribute.
    """

    model_config = SettingsConfigDict(env_file=None)


_ENV_KEYS = (
    "APP_NAME",
    "ENVIRONMENT",
    "DATABASE_URL",
    "LOG_LEVEL",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_ISSUER",
    "OIDC_REALM",
    "OIDC_REDIRECT_URI",
    "OIDC_SCOPE",
    "PROGRAM_GROUP_PREFIX",
    "CORS_ORIGINS",
)


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every Settings-relevant env var so defaults are never masked."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _build_settings(**overrides: Any) -> Settings:
    """Construct Settings hermetically: no stray `.env`, only explicit overrides."""
    return _HermeticSettings(**overrides)


# AUTH-01-TC-12 — exact FR-1 field list and defaults, clean environment.
def test_settings_default_field_list_matches_fr1() -> None:
    settings = _build_settings()

    assert settings.oidc_client_id is None
    assert settings.oidc_client_secret is None
    assert settings.oidc_issuer is None
    assert settings.oidc_realm is None
    assert settings.oidc_scope == "openid profile email groups"
    assert settings.program_group_prefix == "program-"
    assert settings.cors_origins == []


# AUTH-01-TC-12 — "typed str | None" per the expected_results wording.
@pytest.mark.parametrize(
    "field_name",
    ["oidc_client_id", "oidc_client_secret", "oidc_issuer", "oidc_realm"],
)
def test_oidc_identity_fields_are_typed_str_or_none(field_name: str) -> None:
    annotation = Settings.model_fields[field_name].annotation
    assert annotation == (str | None)


# D-11 — explicit redirect_uri override, added after FR-1's field list was
# pinned (AF-08). Optional, defaults to None, does not affect `oidc_configured`.
def test_oidc_redirect_uri_defaults_to_none() -> None:
    settings = _build_settings()
    assert settings.oidc_redirect_uri is None


def test_oidc_redirect_uri_is_typed_str_or_none() -> None:
    annotation = Settings.model_fields["oidc_redirect_uri"].annotation
    assert annotation == (str | None)


def test_oidc_redirect_uri_unset_does_not_affect_oidc_configured() -> None:
    settings = _build_settings(
        oidc_client_id="client", oidc_client_secret="secret", oidc_issuer="https://issuer"
    )
    assert settings.oidc_redirect_uri is None
    assert settings.oidc_configured is True


def test_non_production_environments_is_pinned_frozenset() -> None:
    assert isinstance(NON_PRODUCTION_ENVIRONMENTS, frozenset)
    assert NON_PRODUCTION_ENVIRONMENTS == frozenset({"local", "development", "dev", "test", "ci"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PRODUCTION", "production"),
        ("Prod", "prod"),
    ],
)
def test_environment_is_lowercased_at_load(raw: str, expected: str) -> None:
    settings = _build_settings(environment=raw)
    assert settings.environment == expected


@pytest.mark.parametrize("environment", ["local", "development", "dev", "test", "ci"])
def test_dev_bypass_enabled_true_for_allow_listed_environments(environment: str) -> None:
    settings = _build_settings(environment=environment)
    assert settings.dev_bypass_enabled is True


# D-01 fail-closed: allow-list membership is the sole gate. "produciton" is
# the exact typo research/FR-1 calls out; "staging" is a real, unnamed
# environment; "PRODUCTION"/"Prod" prove lowercasing alone doesn't leak an
# abbreviation through; "" and "unknown" cover unset/unanticipated values.
@pytest.mark.parametrize(
    "environment",
    ["production", "PRODUCTION", "Prod", "prod", "staging", "produciton", "", "unknown"],
)
def test_dev_bypass_enabled_false_fail_closed(environment: str) -> None:
    settings = _build_settings(environment=environment)
    assert settings.dev_bypass_enabled is False


def test_oidc_configured_true_only_when_all_three_present() -> None:
    settings = _build_settings(
        oidc_client_id="client", oidc_client_secret="secret", oidc_issuer="https://issuer"
    )
    assert settings.oidc_configured is True


# TC-13/14/15's boundary: an empty string is falsy, same as None — must not
# be treated as "configured" just because the field is technically set.
@pytest.mark.parametrize(
    ("client_id", "client_secret", "issuer"),
    [
        (None, "secret", "https://issuer"),
        ("client", None, "https://issuer"),
        ("client", "secret", None),
        ("", "secret", "https://issuer"),
        ("client", "", "https://issuer"),
        ("client", "secret", ""),
        (None, None, None),
    ],
)
def test_oidc_configured_false_when_any_field_missing_or_empty(
    client_id: str | None, client_secret: str | None, issuer: str | None
) -> None:
    settings = _build_settings(
        oidc_client_id=client_id, oidc_client_secret=client_secret, oidc_issuer=issuer
    )
    assert settings.oidc_configured is False


# Env-var path (not constructor kwargs) — this is the path that was actually
# broken and fixed via Annotated[list[str], NoDecode] + a before-validator;
# pydantic-settings would otherwise JSON-decode CORS_ORIGINS and raise.
def test_cors_origins_parses_single_bare_origin_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://dashboard.example.com")
    settings = _build_settings()
    assert settings.cors_origins == ["https://dashboard.example.com"]


def test_cors_origins_parses_comma_separated_list_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com,https://b.example.com")
    settings = _build_settings()
    assert settings.cors_origins == ["https://a.example.com", "https://b.example.com"]


def test_cors_origins_from_env_strips_whitespace_around_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", " https://a.example.com , https://b.example.com ")
    settings = _build_settings()
    assert settings.cors_origins == ["https://a.example.com", "https://b.example.com"]
