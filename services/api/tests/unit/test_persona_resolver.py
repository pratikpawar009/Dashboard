"""Unit tests for `app/core/persona_resolver.py`'s `PersonaResolver` --
AUTH-02-TC-01..11, TC-14, TC-15 (`docs/test-cases/AUTH-02.json`).

Bundles tier-precedence, fail-closed, cache-TTL, concurrency, and PII-audit
cases into one topic file, matching how AUTH-01's `test_auth_dev_bypass.py`
bundled 9 TCs spanning multiple categories (D-10). TC-12/TC-13 (performance
baselines) belong to `tests/perf/test_persona_resolver_perf.py` (T-08), not
here.

Fixture split (T-07 task notes): TC-01,02,04,05,06,07,08,11 are pure-mock --
no live DB -- via `FakeSessionFactory` (a hand-rolled Tier-3 stand-in, D-06's
injectable `session_factory` seam). TC-03,14 need a real `persona_config`
row and run against the disposable test Postgres via `migrated_db`/
`test_engine`/`test_session` (`tests/conftest.py`), passing a REAL
`async_sessionmaker(bind=test_engine)` -- exactly per D-06's documented test
convention -- and counting actual Tier-3 SELECTs via a `before_cursor_execute`
listener (mirrors `tests/unit/test_rollup_rebuild_query_plan.py`'s
`_count_usage_events_selects`) rather than wrapping the session factory in a
fake, so `session_factory`'s real `async_sessionmaker[AsyncSession]` type is
never violated for those two tests. TC-09/TC-10 (Tier-2 YAML startup errors)
need neither a live DB nor a working `session_factory` at all -- resolution
never reaches Tier-3 before `PersonaResolver.__init__` itself raises.

`FakeSessionFactory` is intentionally NOT an `async_sessionmaker` -- passing
one to `PersonaResolver(..., session_factory=...)` is narrowed for mypy via
a single `cast` in `_pure_mock_resolver` (mirrors `tests/test_models.py`'s
own `cast(sa.Table, ...)` precedent), since it is structurally compatible at
runtime (callable -> async context manager exposing `.execute()`) without
literally subclassing a concrete SQLAlchemy class.

Hermetic `Settings` construction: `_build_settings` always passes both
`persona_role_map` and `persona_config_file` explicitly (even when `None`).
pydantic-settings' documented precedence (constructor kwargs > env > `.env`
file > field default) makes that enough to keep every test immune to a
stray `services/api/.env` or shell-exported `PERSONA_ROLE_MAP` /
`PERSONA_CONFIG_FILE` -- no other `Settings` field affects persona
resolution, so this file does not need `test_auth_config.py`'s fuller
`_HermeticSettings`/`_clean_settings_env` ceremony (that file also asserts
UNSET-field defaults, which no test here does).

Log-capture idiom: a `_RecordCapturingHandler` attached directly to the real
logger object (`app.core.persona_resolver` for `persona_mapping_loaded`,
`app.core.config` for TC-08's `persona_role_map_parse_error` warning),
force-enabled and depropagated -- `test_auth_logging_security.py`'s
documented idiom, immune to both the `configure_logging()`+`capsys` stdout
trap and Alembic's `fileConfig(disable_existing_loggers=True)` sweep.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
import sqlalchemy as sa
import yaml
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core import persona_resolver
from app.core.config import Settings
from app.core.logging import JSONFormatter
from app.models.ingestion import PersonaConfig
from tests.conftest import AlembicRunner

_PERSONA_CONFIG_RE = re.compile(r"\bpersona_config\b", re.IGNORECASE)


# -----------------------------------------------------------------------------
# Settings / Tier-2 YAML helpers.
# -----------------------------------------------------------------------------


def _build_settings(
    *, tier1_map: dict[str, str] | str | None = None, persona_config_file: Path
) -> Settings:
    """See module docstring "Hermetic `Settings` construction". `tier1_map`
    accepts a raw `str` too (TC-08's invalid-JSON case): `persona_role_map`'s
    `mode="before"` field validator accepts and parses a raw string at
    runtime -- exactly how a real `PERSONA_ROLE_MAP` env var reaches it --
    but the field's declared type is the POST-validation shape, which mypy
    has no visibility into a "before" validator's pre-validation input type
    for. The `cast` reflects that gap, not a real type mismatch."""
    return Settings(
        persona_role_map=cast(dict[str, str] | None, tier1_map),
        persona_config_file=persona_config_file,
    )


def _write_tier2_yaml(tmp_path: Path, mapping: dict[str, str] | None = None) -> Path:
    """Writes a schema-valid Tier-2 YAML stub under `tmp_path`. `mapping`
    omitted or `{}` produces D-02's "empty-but-valid `{}`" shape."""
    path = tmp_path / "persona_role_map.yaml"
    path.write_text(yaml.safe_dump(mapping or {}))
    return path


# -----------------------------------------------------------------------------
# Pure-mock Tier-3 `session_factory` stand-in (D-06) -- no live DB. Implements
# only the two operations `PersonaResolver._resolve_tier3` actually uses:
# the async-context-manager protocol, and `.execute()`.
# -----------------------------------------------------------------------------


class _FakeRow:
    def __init__(self, persona: str) -> None:
        self.persona = persona


class _FakeResult:
    def __init__(self, row: _FakeRow | None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> _FakeRow | None:
        return self._row


class _FakeSessionCtx:
    def __init__(self, persona: str | None, delay_seconds: float) -> None:
        self._persona = persona
        self._delay_seconds = delay_seconds

    async def __aenter__(self) -> _FakeSessionCtx:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        return None

    async def execute(self, _stmt: Any) -> _FakeResult:
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        row = _FakeRow(self._persona) if self._persona is not None else None
        return _FakeResult(row)


class FakeSessionFactory:
    """`call_count` records how many times Tier-3 was actually queried --
    every "Tier-3 not consulted" / "exactly one Tier-3 query" assertion in
    this file reads it directly rather than trusting that `resolve()`
    merely returned the right value."""

    def __init__(self, persona: str | None = None, delay_seconds: float = 0.0) -> None:
        self.persona = persona
        self.delay_seconds = delay_seconds
        self.call_count = 0

    def __call__(self) -> _FakeSessionCtx:
        self.call_count += 1
        return _FakeSessionCtx(self.persona, self.delay_seconds)


def _pure_mock_resolver(
    settings: Settings, session_factory: FakeSessionFactory
) -> persona_resolver.PersonaResolver:
    """See module docstring for why the `cast` is safe here."""
    return persona_resolver.PersonaResolver(
        settings, session_factory=cast(async_sessionmaker[AsyncSession], session_factory)
    )


# -----------------------------------------------------------------------------
# Fake monotonic clock (TC-06) -- advances only when told to.
# -----------------------------------------------------------------------------


class _FakeClock:
    """Callable stand-in for `time.monotonic`. Patched onto the real, shared
    `time` module for one test's duration via `monkeypatch.setattr(
    persona_resolver.time, "monotonic", clock)` -- reverted automatically.
    Safe here: the critical section under test performs no other timed/
    awaited I/O that needs real wall-clock progress."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# -----------------------------------------------------------------------------
# Log capture -- mirrors test_auth_logging_security.py's documented idiom.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_logger(name: str, level: int = logging.INFO) -> Iterator[list[logging.LogRecord]]:
    logger = logging.getLogger(name)
    original_disabled = logger.disabled
    original_propagate = logger.propagate
    original_level = logger.level
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(level)
    handler = _RecordCapturingHandler()
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.disabled = original_disabled
        logger.propagate = original_propagate
        logger.setLevel(original_level)


@pytest.fixture
def persona_logger_records() -> Iterator[list[logging.LogRecord]]:
    """Captures records from the real `app.core.persona_resolver` logger."""
    with _capture_logger("app.core.persona_resolver") as records:
        yield records


def _mapping_events(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [r for r in records if r.getMessage() == "persona_mapping_loaded"]


# -----------------------------------------------------------------------------
# Live-DB Tier-3 query counter (TC-03, TC-14) -- mirrors
# test_rollup_rebuild_query_plan.py's `_count_usage_events_selects`.
# -----------------------------------------------------------------------------


class _SelectCounter:
    def __init__(self) -> None:
        self.count = 0


@contextmanager
def _count_persona_config_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if statement.strip().upper().startswith("SELECT") and _PERSONA_CONFIG_RE.search(statement):
            counter.count += 1

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


# -----------------------------------------------------------------------------
# AUTH-02-TC-01 (AC-1/FR-1) -- Tier-1 resolves without consulting Tier-2/3.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier1_resolves_without_consulting_tier2_or_tier3_tc01(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    """Tier-2 loading is eager at `__init__` (D-05), not per-call, so "no
    Tier-2 file read" is verified as "not USED to produce the result", not
    "file never opened": Tier-2 deliberately lacks 'cio', so an incorrect
    fall-through past Tier-1 would either miss (proving via a different
    persona/tier) or reach Tier-3 (`session_factory.call_count` would be
    non-zero) -- neither happens."""
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map={"cio": "cio"}, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory()
    resolver = _pure_mock_resolver(settings, session_factory)

    persona = await resolver.resolve("cio")

    assert persona == "cio"
    assert session_factory.call_count == 0
    events = _mapping_events(persona_logger_records)
    assert len(events) == 1
    assert events[0].role == "cio"  # type: ignore[attr-defined]
    assert events[0].persona == "cio"  # type: ignore[attr-defined]
    assert events[0].tier == "tier-1-env"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-02-TC-02 (AC-2/FR-2) -- Tier-2 YAML fallback when Tier-1 is absent.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier2_yaml_fallback_when_tier1_absent_tc02(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {"developer": "developer"})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory()
    resolver = _pure_mock_resolver(settings, session_factory)

    persona = await resolver.resolve("developer")

    assert persona == "developer"
    assert session_factory.call_count == 0  # Tier-3 not consulted
    events = _mapping_events(persona_logger_records)
    assert len(events) == 1
    assert events[0].tier == "tier-2-yaml"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-02-TC-03 (AC-3/FR-3) -- Tier-3 Postgres fallback. Live DB.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier3_postgres_fallback_when_tier1_tier2_absent_tc03(
    migrated_db: AlembicRunner,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    tmp_path: Path,
    persona_logger_records: list[logging.LogRecord],
) -> None:
    await test_session.execute(
        sa.insert(PersonaConfig).values(role="architect", persona="architect")
    )
    await test_session.commit()

    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    resolver = persona_resolver.PersonaResolver(
        settings, session_factory=async_sessionmaker(bind=test_engine, expire_on_commit=False)
    )

    with _count_persona_config_selects(test_engine) as counter:
        persona = await resolver.resolve("architect")

    assert persona == "architect"
    assert counter.count == 1
    events = _mapping_events(persona_logger_records)
    assert len(events) == 1
    assert events[0].tier == "tier-3-postgres"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-02-TC-04 (AC-4) -- all tiers empty raises PersonaNotFoundError.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_tiers_empty_raises_persona_not_found_error_tc04(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(persona=None)  # Tier-3 miss too
    resolver = _pure_mock_resolver(settings, session_factory)

    with pytest.raises(persona_resolver.PersonaNotFoundError) as exc_info:
        await resolver.resolve("unmapped_role")

    assert exc_info.value.role == "unmapped_role"
    assert session_factory.call_count == 1  # Tier-3 WAS consulted (final miss)
    assert _mapping_events(persona_logger_records) == []  # a raise is never logged


# -----------------------------------------------------------------------------
# AUTH-02-TC-05 (AC-5) -- warm cache hit. Both halves matter: no re-query,
# AND persona_mapping_loaded still fires on the cache-hit call.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warm_cache_hit_returns_cached_persona_without_rereading_tc05(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(persona="product-manager")
    resolver = _pure_mock_resolver(settings, session_factory)

    first = await resolver.resolve("product-manager")
    second = await resolver.resolve("product-manager")

    assert first == second == "product-manager"
    assert session_factory.call_count == 1  # only the cold first call queried Tier-3
    events = _mapping_events(persona_logger_records)
    assert len(events) == 2  # emitted on BOTH calls, cache hit included
    assert events[0].tier == events[1].tier == "tier-3-postgres"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-02-TC-06 (AC-6) -- cache expiry after the 300s TTL re-reads sources.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_expiry_after_ttl_rereads_sources_tc06(
    tmp_path: Path,
    persona_logger_records: list[logging.LogRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(persona="engineering-manager")
    resolver = _pure_mock_resolver(settings, session_factory)

    clock = _FakeClock(start=1_000.0)
    monkeypatch.setattr(persona_resolver.time, "monotonic", clock)

    first = await resolver.resolve("engineering-manager")
    clock.advance(301.0)  # > 300s TTL
    second = await resolver.resolve("engineering-manager")

    assert first == second == "engineering-manager"
    assert session_factory.call_count == 2  # re-queried after expiry
    events = _mapping_events(persona_logger_records)
    assert len(events) == 2
    assert events[1].tier == "tier-3-postgres"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-02-TC-07 (AC-7/D-03) -- data-driven custom role mapping via Tier-2.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_driven_custom_role_mapping_tc07(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {"board_member": "cio"})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory()
    resolver = _pure_mock_resolver(settings, session_factory)

    persona = await resolver.resolve("board_member")

    assert persona == "cio"
    assert session_factory.call_count == 0
    events = _mapping_events(persona_logger_records)
    assert events[0].tier == "tier-2-yaml"  # type: ignore[attr-defined]

    # D-03 / AC-7 third bullet: fully data-driven, no hardcoded role branch.
    source = Path(persona_resolver.__file__).read_text(encoding="utf-8")
    assert "board_member" not in source
    assert "cxo" not in source


# -----------------------------------------------------------------------------
# AUTH-02-TC-08 (FR-1) -- unparseable Tier-1 JSON warns and falls through.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier1_unparseable_json_logs_warning_falls_through_tc08(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})

    with _capture_logger("app.core.config", level=logging.WARNING) as config_records:
        settings = _build_settings(tier1_map="{cio: cio}", persona_config_file=tier2_path)

    assert settings.persona_role_map is None
    warnings = [r for r in config_records if r.getMessage() == "persona_role_map_parse_error"]
    assert len(warnings) == 1

    session_factory = FakeSessionFactory(persona="cio")
    resolver = _pure_mock_resolver(settings, session_factory)
    persona = await resolver.resolve("cio")

    assert persona == "cio"
    assert session_factory.call_count == 1  # fell through to Tier-3
    events = _mapping_events(persona_logger_records)
    assert events[-1].tier == "tier-3-postgres"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-02-TC-09 (FR-2) -- missing Tier-2 YAML file is a startup error.
# -----------------------------------------------------------------------------


def test_missing_tier2_yaml_raises_file_not_found_error_tc09(tmp_path: Path) -> None:
    missing_path = tmp_path / "does-not-exist.yaml"
    settings = _build_settings(tier1_map=None, persona_config_file=missing_path)

    with pytest.raises(FileNotFoundError):
        _pure_mock_resolver(settings, FakeSessionFactory())


# -----------------------------------------------------------------------------
# AUTH-02-TC-10 (FR-2) -- malformed Tier-2 YAML is a startup error.
# -----------------------------------------------------------------------------


def test_malformed_tier2_yaml_raises_yaml_error_tc10(tmp_path: Path) -> None:
    path = tmp_path / "persona_role_map.yaml"
    path.write_text("cio: cio\n  developer: developer\n")  # invalid indentation

    settings = _build_settings(tier1_map=None, persona_config_file=path)

    with pytest.raises(yaml.YAMLError):
        _pure_mock_resolver(settings, FakeSessionFactory())


# -----------------------------------------------------------------------------
# AUTH-02-TC-11 (FR-3) -- Tier-3 query timeout raises PersonaResolutionError.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier3_query_timeout_raises_persona_resolution_error_tc11(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tier-3 mocked to sleep past the timeout, per the test-case's own
    precondition text. `_TIER3_TIMEOUT_SECONDS` is monkeypatched down for
    test speed; the raised message is a hardcoded literal in the resolver
    source (D-08's sibling detail: `extra={"timestamp": ...}` is inert for
    the same reason this string isn't computed from the constant), so the
    assertion below is unaffected by the patched value."""
    monkeypatch.setattr(persona_resolver, "_TIER3_TIMEOUT_SECONDS", 0.05)
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(persona="ignored", delay_seconds=0.2)
    resolver = _pure_mock_resolver(settings, session_factory)

    with pytest.raises(persona_resolver.PersonaResolutionError) as exc_info:
        await resolver.resolve("slow_role")

    assert exc_info.value.role == "slow_role"
    assert "Tier-3 query timeout after 3.0s" in str(exc_info.value)


# -----------------------------------------------------------------------------
# AUTH-02-TC-14 (NFR-observability/D-04) -- 10 concurrent cold calls collapse
# to exactly 1 Tier-3 query. Live DB.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_resolve_calls_collapse_to_one_tier3_query_tc14(
    migrated_db: AlembicRunner,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    tmp_path: Path,
) -> None:
    await test_session.execute(
        sa.insert(PersonaConfig).values(role="developer", persona="developer")
    )
    await test_session.commit()

    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    resolver = persona_resolver.PersonaResolver(
        settings, session_factory=async_sessionmaker(bind=test_engine, expire_on_commit=False)
    )

    with _count_persona_config_selects(test_engine) as counter:
        tasks = [asyncio.create_task(resolver.resolve("developer")) for _ in range(10)]
        results = await asyncio.gather(*tasks)

    assert results == ["developer"] * 10
    assert counter.count == 1


# -----------------------------------------------------------------------------
# AUTH-02-TC-15 (FR-5/NFR-security/NFR-observability) -- persona_mapping_loaded
# carries exactly the PII-safe field allowlist.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persona_mapping_loaded_event_contains_no_pii_tc15(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map={"cio": "cio"}, persona_config_file=tier2_path)
    resolver = _pure_mock_resolver(settings, FakeSessionFactory())

    await resolver.resolve("cio")

    events = _mapping_events(persona_logger_records)
    assert len(events) == 1
    payload = json.loads(JSONFormatter().format(events[0]))

    # Allowlist, not a denylist (task instruction): the emitted payload's key
    # set must equal exactly the resolver-supplied fields plus JSONFormatter's
    # own first-class meta -- no `cached` field, no request/user context.
    assert set(payload.keys()) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "role",
        "persona",
        "tier",
    }
    assert payload["role"] == "cio"
    assert payload["persona"] == "cio"
    assert payload["tier"] == "tier-1-env"


# -----------------------------------------------------------------------------
# AUTH-02-TC-16 (persona-resolver contract § observability / REQUIREMENTS.md C-4)
# -- a FRESH Tier-3 resolution carries tier3_latency_ms; nothing else does.
#
# Added during the Step 2 fix loop. The contract in docs/requirements/auth.md
# ("a tier-3 hit additionally carries tier3_latency_ms"), REQUIREMENTS.md C-4,
# the NFR that alerts when its p95 exceeds 200ms, and T-05's own task note all
# require this field; the first implementation omitted it. FR-5's "nothing
# else" bars user context, not this non-PII operational measure -- so TC-15's
# exact allowlist still holds for the Tier-1 event it asserts, and the field
# appears only where the contract puts it.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_tier3_hit_carries_tier3_latency_ms_tc16(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map={}, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(persona="architect")
    resolver = _pure_mock_resolver(settings, session_factory)

    persona = await resolver.resolve("solution-architect")

    assert persona == "architect"
    events = _mapping_events(persona_logger_records)
    assert len(events) == 1
    payload = json.loads(JSONFormatter().format(events[0]))

    assert payload["tier"] == "tier-3-postgres"
    assert "tier3_latency_ms" in payload
    assert isinstance(payload["tier3_latency_ms"], (int, float))
    assert payload["tier3_latency_ms"] >= 0.0
    # Still no PII: the Tier-3 event is TC-15's allowlist plus exactly one field.
    assert set(payload.keys()) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "role",
        "persona",
        "tier",
        "tier3_latency_ms",
    }


@pytest.mark.asyncio
async def test_tier1_and_tier2_hits_omit_tier3_latency_ms_tc16(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {"qa-lead": "developer"})
    settings = _build_settings(tier1_map={"cio": "cio"}, persona_config_file=tier2_path)
    resolver = _pure_mock_resolver(settings, FakeSessionFactory())

    await resolver.resolve("cio")  # Tier-1
    await resolver.resolve("qa-lead")  # Tier-2

    events = _mapping_events(persona_logger_records)
    assert len(events) == 2
    for record in events:
        payload = json.loads(JSONFormatter().format(record))
        assert "tier3_latency_ms" not in payload, payload["tier"]


@pytest.mark.asyncio
async def test_warm_hit_reusing_tier3_omits_tier3_latency_ms_tc16(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    """A cached Tier-3 value ran no query, so re-emitting the original
    measurement would double-count every cached read into the p95 the NFR
    alerts on. The warm event keeps `tier: tier-3-postgres` but drops the
    latency."""
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map={}, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(persona="architect")
    resolver = _pure_mock_resolver(settings, session_factory)

    await resolver.resolve("solution-architect")  # cold -- carries latency
    await resolver.resolve("solution-architect")  # warm -- must not

    events = _mapping_events(persona_logger_records)
    assert len(events) == 2
    cold = json.loads(JSONFormatter().format(events[0]))
    warm = json.loads(JSONFormatter().format(events[1]))

    assert session_factory.call_count == 1
    assert "tier3_latency_ms" in cold
    assert warm["tier"] == "tier-3-postgres"
    assert "tier3_latency_ms" not in warm
