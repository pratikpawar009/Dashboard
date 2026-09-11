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

Hermetic `Settings` construction: `_build_settings` always passes
`persona_role_map`, `persona_config_file`, and (AUTH-07-FR-6/AC-20)
`persona_precedence_order` explicitly (even when `None`). pydantic-settings'
documented precedence (constructor kwargs > env > `.env` file > field
default) makes that enough to keep every test immune to a stray
`services/api/.env` or shell-exported `PERSONA_ROLE_MAP` /
`PERSONA_CONFIG_FILE` / `PERSONA_PRECEDENCE_ORDER` -- no other `Settings`
field affects persona resolution, so this file does not need
`test_auth_config.py`'s fuller `_HermeticSettings`/`_clean_settings_env`
ceremony (that file also asserts UNSET-field defaults, which no test here
does).

AUTH-07-AC-20/FR-6 (T-04) tests exercise `PersonaResolver`'s private
precedence-loading methods (`_resolve_precedence_order` and friends)
directly, the same way T-01's own tests exercised
`Settings.persona_precedence_order` before any resolver code consumed it --
T-05 (DECISIONS.md D-06) is what wires a public `resolve_precedence` entry
point on top of this loading mechanism.

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
from app.models.ingestion import PersonaConfig, PersonaPrecedence
from tests.conftest import AlembicRunner

_PERSONA_CONFIG_RE = re.compile(r"\bpersona_config\b", re.IGNORECASE)
_PERSONA_PRECEDENCE_RE = re.compile(r"\bpersona_precedence\b", re.IGNORECASE)


# -----------------------------------------------------------------------------
# Settings / Tier-2 YAML helpers.
# -----------------------------------------------------------------------------


def _build_settings(
    *,
    tier1_map: dict[str, str] | str | None = None,
    persona_config_file: Path,
    precedence_order: list[str] | None = None,
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
        persona_precedence_order=precedence_order,
    )


def _write_tier2_yaml(tmp_path: Path, mapping: dict[str, str] | None = None) -> Path:
    """Writes a schema-valid Tier-2 YAML stub under `tmp_path`. `mapping`
    omitted or `{}` produces D-02's "empty-but-valid `{}`" shape."""
    path = tmp_path / "persona_role_map.yaml"
    path.write_text(yaml.safe_dump(mapping or {}))
    return path


def _write_tier2_yaml_with_precedence(
    tmp_path: Path, mapping: dict[str, str] | None = None, *, precedence: object
) -> Path:
    """Like `_write_tier2_yaml`, but also writes a root-level `precedence:`
    key (AUTH-07-FR-6/AC-20) alongside the role map in the SAME document --
    the real shape `PersonaResolver.__init__` must pop apart before
    casefolding the role map. `precedence` accepts any YAML-serializable
    value, including a deliberately malformed one (a bare string, a list of
    non-strings), so callers can exercise
    `_validate_tier2_precedence_order`'s startup-failure path as well as its
    happy path."""
    document: dict[str, object] = dict(mapping or {})
    document["precedence"] = precedence
    path = tmp_path / "persona_role_map.yaml"
    path.write_text(yaml.safe_dump(document))
    return path


# -----------------------------------------------------------------------------
# Pure-mock Tier-3 `session_factory` stand-in (D-06) -- no live DB. Implements
# only the two operations `PersonaResolver._resolve_tier3` actually uses:
# the async-context-manager protocol, and `.execute()`.
# -----------------------------------------------------------------------------


class _FakeRow:
    def __init__(self, persona: str) -> None:
        self.persona = persona


class _FakeScalars:
    """Stands in for SQLAlchemy's `Result.scalars()` -- production code
    (`PersonaResolver._resolve_tier3`) now calls `.scalars().all()` instead
    of `.scalar_one_or_none()` so it can detect a same-tier Tier-3 collision
    (>1 distinct persona for one casefolded role, AC-22), not just a single
    hit/miss."""

    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows

    def all(self) -> list[_FakeRow]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSessionCtx:
    def __init__(self, personas: list[str], delay_seconds: float) -> None:
        self._personas = personas
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
        return _FakeResult([_FakeRow(p) for p in self._personas])


class FakeSessionFactory:
    """`call_count` records how many times Tier-3 was actually queried --
    every "Tier-3 not consulted" / "exactly one Tier-3 query" assertion in
    this file reads it directly rather than trusting that `resolve()`
    merely returned the right value.

    `persona` is the single-row shape every pre-existing test uses.
    `personas` (plural) is for AC-22's Tier-3 same-tier-collision case,
    where the fake row set must carry more than one distinct persona for
    the one casefolded role queried; it takes precedence over `persona`
    when both are given."""

    def __init__(
        self,
        persona: str | None = None,
        personas: list[str] | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.persona = persona
        self.personas = personas
        self.delay_seconds = delay_seconds
        self.call_count = 0

    def __call__(self) -> _FakeSessionCtx:
        self.call_count += 1
        rows = self.personas if self.personas is not None else (
            [self.persona] if self.persona is not None else []
        )
        return _FakeSessionCtx(rows, self.delay_seconds)


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


def _not_found_events(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    """AUTH-07-AC-25/FR-8 counterpart to `_mapping_events`, for the new
    `persona_mapping_not_found` event (D-04)."""
    return [r for r in records if r.getMessage() == "persona_mapping_not_found"]


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


@contextmanager
def _count_persona_precedence_selects(engine: AsyncEngine) -> Iterator[_SelectCounter]:
    """AUTH-07-AC-20/FR-6 counterpart to `_count_persona_config_selects`, for
    the new `persona_precedence` Tier-3 query."""
    counter = _SelectCounter()
    sync_engine = engine.sync_engine

    def _before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if statement.strip().upper().startswith(
            "SELECT"
        ) and _PERSONA_PRECEDENCE_RE.search(statement):
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


# -----------------------------------------------------------------------------
# AUTH-07-AC-21 (T-03 task note) -- regression: today's shipped, exact-case
# Tier-2 mappings (services/api/config/persona_role_map.yaml) still resolve
# identically post-casefold change. Casefolding may only ADD matches, never
# change or break an existing exact-case one.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac21_shipped_exact_case_mappings_still_resolve_identically(
    tmp_path: Path,
) -> None:
    shipped_mapping = {
        "cio": "cio",
        "architect": "architect",
        "developer": "developer",
        "product-manager": "product-manager",
        "engineering-manager": "engineering-manager",
    }
    tier2_path = _write_tier2_yaml(tmp_path, shipped_mapping)
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    resolver = _pure_mock_resolver(settings, FakeSessionFactory())

    for role, expected_persona in shipped_mapping.items():
        assert await resolver.resolve(role) == expected_persona


# -----------------------------------------------------------------------------
# AUTH-07-AC-18/FR-7 -- casefolded lookup matches a differently-cased role at
# Tier-1 and Tier-2, without falling through to Tier-3.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac18_tier1_casefold_matches_differently_cased_role(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map={"cio": "cio"}, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory()
    resolver = _pure_mock_resolver(settings, session_factory)

    persona = await resolver.resolve("CIO")

    assert persona == "cio"
    assert session_factory.call_count == 0
    events = _mapping_events(persona_logger_records)
    assert events[0].tier == "tier-1-env"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_ac18_tier2_casefold_matches_differently_cased_role(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {"architect": "architect"})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory()
    resolver = _pure_mock_resolver(settings, session_factory)

    persona = await resolver.resolve("Architect")

    assert persona == "architect"
    assert session_factory.call_count == 0  # matched at Tier-2, never reached Tier-3
    events = _mapping_events(persona_logger_records)
    assert events[0].tier == "tier-2-yaml"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-07-AC-22/D-03 -- same-tier case collision. Tier-1/Tier-2 raise at
# PersonaResolver construction; Tier-3 raises at resolve time (its data can
# change without a restart).
# -----------------------------------------------------------------------------


def test_ac22_tier1_same_tier_case_collision_raises_at_construction(tmp_path: Path) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(
        tier1_map={"Developer": "developer", "developer": "cio"},
        persona_config_file=tier2_path,
    )

    with pytest.raises(persona_resolver.PersonaResolutionError) as exc_info:
        _pure_mock_resolver(settings, FakeSessionFactory())

    assert exc_info.value.reason == "ambiguous_case_collision"
    assert exc_info.value.role == "developer"


def test_ac22_tier2_same_tier_case_collision_raises_at_construction(tmp_path: Path) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {"Architect": "architect", "architect": "cio"})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)

    with pytest.raises(persona_resolver.PersonaResolutionError) as exc_info:
        _pure_mock_resolver(settings, FakeSessionFactory())

    assert exc_info.value.reason == "ambiguous_case_collision"
    assert exc_info.value.role == "architect"


@pytest.mark.asyncio
async def test_ac22_tier3_same_tier_case_collision_raises_at_resolve_time_pure_mock(
    tmp_path: Path,
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(personas=["architect", "developer"])
    resolver = _pure_mock_resolver(settings, session_factory)

    with pytest.raises(persona_resolver.PersonaResolutionError) as exc_info:
        await resolver.resolve("Architect")

    assert exc_info.value.reason == "ambiguous_case_collision"
    assert exc_info.value.role == "architect"  # the casefolded role, per D-03


@pytest.mark.asyncio
async def test_ac22_tier3_same_tier_case_collision_raises_at_resolve_time_live_db(
    migrated_db: AlembicRunner,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Live-DB counterpart to the pure-mock case above: two distinct
    `persona_config` primary keys (`Architect`, `architect`) that casefold
    to the same lookup key, exercising the real `func.lower()` `WHERE`
    clause rather than the fake session's in-memory dedupe."""
    await test_session.execute(
        sa.insert(PersonaConfig).values(role="Architect", persona="architect")
    )
    await test_session.execute(
        sa.insert(PersonaConfig).values(role="architect", persona="developer")
    )
    await test_session.commit()

    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    resolver = persona_resolver.PersonaResolver(
        settings, session_factory=async_sessionmaker(bind=test_engine, expire_on_commit=False)
    )

    with pytest.raises(persona_resolver.PersonaResolutionError) as exc_info:
        await resolver.resolve("ARCHITECT")

    assert exc_info.value.reason == "ambiguous_case_collision"
    assert exc_info.value.role == "architect"


# -----------------------------------------------------------------------------
# AUTH-07-AC-23/FR-7 -- the per-role cache key is the casefolded role string:
# case variants of the same role share one entry, never alternating between
# hit and miss on casing alone.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac23_casefolded_cache_key_shared_across_case_variants(
    tmp_path: Path,
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(persona="architect")
    resolver = _pure_mock_resolver(settings, session_factory)

    first = await resolver.resolve("Architect")
    second = await resolver.resolve("architect")
    third = await resolver.resolve("ARCHITECT")

    assert first == second == third == "architect"
    assert session_factory.call_count == 1  # one shared cache entry, not one per casing


# -----------------------------------------------------------------------------
# AUTH-07-AC-20/FR-6 (T-04) -- persona-precedence order loading through the
# SAME 3-tier fallthrough + hardcoded default + 300s cache the role-mapping
# tiers already use. `resolver._resolve_precedence_order()` is exercised
# directly -- T-05 (DECISIONS.md D-06) is what wires a public
# `resolve_precedence` selection method on top of this loading mechanism.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac20_tier1_precedence_order_used_without_consulting_tier2_or_tier3(
    tmp_path: Path,
) -> None:
    """Tier-2 deliberately carries a DIFFERENT order, so a wrong fall-through
    past Tier-1 would be visible as a mismatched result, not just a stray
    Tier-3 query."""
    tier2_path = _write_tier2_yaml_with_precedence(
        tmp_path, precedence=["developer", "cio"]
    )
    settings = _build_settings(
        tier1_map=None,
        persona_config_file=tier2_path,
        precedence_order=["architect", "cio"],
    )
    session_factory = FakeSessionFactory()
    resolver = _pure_mock_resolver(settings, session_factory)

    order = await resolver._resolve_precedence_order()

    assert order == ["architect", "cio"]
    assert session_factory.call_count == 0


@pytest.mark.asyncio
async def test_ac20_tier2_precedence_order_used_when_tier1_absent(tmp_path: Path) -> None:
    tier2_path = _write_tier2_yaml_with_precedence(
        tmp_path, precedence=["developer", "architect", "cio"]
    )
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory()
    resolver = _pure_mock_resolver(settings, session_factory)

    order = await resolver._resolve_precedence_order()

    assert order == ["developer", "architect", "cio"]
    assert session_factory.call_count == 0  # Tier-3 not consulted

    # The "precedence" key must never leak into the role map itself.
    assert "precedence" not in resolver._tier2_map


@pytest.mark.asyncio
async def test_ac20_tier3_precedence_fallback_when_tier1_tier2_absent_pure_mock(
    tmp_path: Path,
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(personas=["developer", "architect", "cio"])
    resolver = _pure_mock_resolver(settings, session_factory)

    order = await resolver._resolve_precedence_order()

    assert order == ["developer", "architect", "cio"]
    assert session_factory.call_count == 1


@pytest.mark.asyncio
async def test_ac20_tier3_persona_precedence_table_fallback_live_db(
    migrated_db: AlembicRunner,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Live-DB counterpart: rows are inserted OUT of rank order, so a
    passing assertion actually exercises the real `ORDER BY rank` clause
    rather than merely echoing insertion order."""
    await test_session.execute(sa.insert(PersonaPrecedence).values(rank=2, persona="cio"))
    await test_session.execute(sa.insert(PersonaPrecedence).values(rank=0, persona="developer"))
    await test_session.execute(sa.insert(PersonaPrecedence).values(rank=1, persona="architect"))
    await test_session.commit()

    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    resolver = persona_resolver.PersonaResolver(
        settings, session_factory=async_sessionmaker(bind=test_engine, expire_on_commit=False)
    )

    with _count_persona_precedence_selects(test_engine) as counter:
        order = await resolver._resolve_precedence_order()

    assert order == ["developer", "architect", "cio"]
    assert counter.count == 1


@pytest.mark.asyncio
async def test_ac20_all_tiers_unset_falls_back_to_hardcoded_default_order(
    tmp_path: Path,
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(personas=None)  # empty persona_precedence table
    resolver = _pure_mock_resolver(settings, session_factory)

    order = await resolver._resolve_precedence_order()

    assert order == [
        "cio",
        "architect",
        "product-manager",
        "engineering-manager",
        "developer",
    ]
    assert session_factory.call_count == 1  # Tier-3 WAS consulted (found nothing)


def test_ac20_malformed_tier2_precedence_not_a_list_raises_value_error(tmp_path: Path) -> None:
    tier2_path = _write_tier2_yaml_with_precedence(tmp_path, precedence="cio,architect")
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)

    with pytest.raises(ValueError, match="precedence"):
        _pure_mock_resolver(settings, FakeSessionFactory())


def test_ac20_malformed_tier2_precedence_non_string_element_raises_value_error(
    tmp_path: Path,
) -> None:
    tier2_path = _write_tier2_yaml_with_precedence(tmp_path, precedence=["cio", 7])
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)

    with pytest.raises(ValueError, match="precedence"):
        _pure_mock_resolver(settings, FakeSessionFactory())


@pytest.mark.asyncio
async def test_ac20_precedence_order_cached_within_ttl_then_rereads_after_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(personas=["architect", "cio"])
    resolver = _pure_mock_resolver(settings, session_factory)

    clock = _FakeClock(start=1_000.0)
    monkeypatch.setattr(persona_resolver.time, "monotonic", clock)

    first = await resolver._resolve_precedence_order()
    second = await resolver._resolve_precedence_order()  # warm, within TTL
    assert first == second == ["architect", "cio"]
    assert session_factory.call_count == 1

    clock.advance(301.0)  # > 300s TTL
    third = await resolver._resolve_precedence_order()

    assert third == ["architect", "cio"]
    assert session_factory.call_count == 2  # re-queried after expiry


@pytest.mark.asyncio
async def test_ac20_precedence_cache_key_never_collides_with_a_real_role_cache_entry(
    tmp_path: Path,
) -> None:
    """The precedence order and a per-role resolution live in separate cache
    structures (DATA-DESIGN.md AUTH-07 §6) -- resolving a role and loading
    the precedence order in either sequence must not interfere with each
    other's cached value or call count."""
    tier2_path = _write_tier2_yaml_with_precedence(
        tmp_path, mapping={"cio": "cio"}, precedence=["cio", "architect"]
    )
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory()
    resolver = _pure_mock_resolver(settings, session_factory)

    persona = await resolver.resolve("cio")
    order = await resolver._resolve_precedence_order()

    assert persona == "cio"
    assert order == ["cio", "architect"]
    assert session_factory.call_count == 0  # both hit at Tier-2, Tier-3 untouched


@pytest.mark.asyncio
async def test_ac20_tier3_precedence_query_timeout_raises_persona_resolution_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(persona_resolver, "_TIER3_TIMEOUT_SECONDS", 0.05)
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(personas=["cio"], delay_seconds=0.2)
    resolver = _pure_mock_resolver(settings, session_factory)

    with pytest.raises(persona_resolver.PersonaResolutionError) as exc_info:
        await resolver._resolve_precedence_order()

    assert exc_info.value.role == "persona-precedence-order"
    assert "Tier-3 precedence query timeout after 3.0s" in str(exc_info.value)


# -----------------------------------------------------------------------------
# AUTH-07-AC-19/FR-6 (T-05) -- `resolve_precedence`: multi-role precedence
# selection on top of T-04's precedence-order loader.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac19_multirole_precedence_selects_architect_regardless_of_order_auth07_tc01(
    tmp_path: Path,
) -> None:
    """AUTH-07-TC-01 (docs/test-cases/AUTH-07.json) at the resolver-unit
    level -- the live 2026-09-10 regression: a token's
    `realm_access.roles` carrying `architect` and `developer` (in any
    order, any case) must resolve to `architect` on every call, since
    `architect` outranks `developer` in the default precedence order. The
    full end-to-end assertion (via `GET /api/me`) lives in
    `tests/unit/test_me.py` per DECISIONS.md D-07; this test exercises
    `PersonaResolver.resolve_precedence` directly.

    Tier-2 carries BOTH the shipped role map and an explicit `precedence:`
    override matching the hardcoded default order, so this is a pure Tier-2,
    zero-I/O path end to end -- role mapping AND precedence order both
    resolve from data already loaded into memory at `__init__`. This is the
    task's own NFR-performance regression guard: ranking introduces no new
    Tier-3 query on top of the tier lookups the roles already needed.
    """
    tier2_path = _write_tier2_yaml_with_precedence(
        tmp_path,
        mapping={"architect": "architect", "developer": "developer"},
        precedence=["cio", "architect", "product-manager", "engineering-manager", "developer"],
    )
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory()
    resolver = _pure_mock_resolver(settings, session_factory)

    for roles in (
        ["Architect", "Developer", "developer"],
        ["developer", "Developer", "Architect"],
        ["developer", "Architect", "Developer"],
    ):
        winner = await resolver.resolve_precedence(roles)
        assert winner == "architect"

    assert session_factory.call_count == 0  # NFR-performance: no Tier-3 I/O at all


@pytest.mark.asyncio
async def test_resolve_precedence_winner_by_precedence_order_not_token_position(
    tmp_path: Path,
) -> None:
    """Distinguishes precedence-driven selection from "first surviving role
    in token order wins" -- a materially different, wrong algorithm. `cio`
    is LAST in the token array but FIRST in precedence order, so it must
    still win."""
    tier2_path = _write_tier2_yaml(tmp_path, {"cio": "cio", "developer": "developer"})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory()
    resolver = _pure_mock_resolver(settings, session_factory)

    winner = await resolver.resolve_precedence(["developer", "cio"])

    assert winner == "cio"


@pytest.mark.asyncio
async def test_resolve_precedence_no_candidate_in_precedence_order_raises_not_found(
    tmp_path: Path,
) -> None:
    """AC-26 fail-closed edge case: a role DOES map to a persona at Tier-2,
    but that persona is absent from the (operator-configured) precedence
    order entirely -- there is no winner to pick, so this must still raise
    `PersonaNotFoundError`, not silently return an unranked persona's
    role."""
    tier2_path = _write_tier2_yaml_with_precedence(
        tmp_path, mapping={"developer": "developer"}, precedence=["cio", "architect"]
    )
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory()
    resolver = _pure_mock_resolver(settings, session_factory)

    with pytest.raises(persona_resolver.PersonaNotFoundError):
        await resolver.resolve_precedence(["developer"])


@pytest.mark.asyncio
async def test_resolve_precedence_bounded_tier3_queries_live_db(
    migrated_db: AlembicRunner,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """AUTH-07-NFR-performance, SINGLE cold call: resolving several
    candidate roles issues at most one Tier-3 `persona_config` SELECT per
    role that actually needs it (never a query per precedence-order entry
    -- ranking itself is in-process only), plus at most one Tier-3
    `persona_precedence` SELECT for the order, regardless of how many
    personas the default order lists.

    This bounds the FIRST, cold-cache call only -- it does not by itself
    prove a REPEATED call for the same roles is cheaper. That warm-cache
    reuse guarantee (AUTH-07-AC-7) is
    `test_resolve_precedence_repeated_call_reuses_warm_cache_auth07_ac07`,
    directly below."""
    await test_session.execute(
        sa.insert(PersonaConfig).values(role="architect", persona="architect")
    )
    await test_session.commit()

    tier2_path = _write_tier2_yaml(tmp_path, {})  # "qa" and "architect" both miss Tier-1/2
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    resolver = persona_resolver.PersonaResolver(
        settings, session_factory=async_sessionmaker(bind=test_engine, expire_on_commit=False)
    )

    with (
        _count_persona_config_selects(test_engine) as role_counter,
        _count_persona_precedence_selects(test_engine) as order_counter,
    ):
        winner = await resolver.resolve_precedence(["qa", "architect"])

    assert winner == "architect"
    assert role_counter.count == 2  # one per surviving role attempted ("qa", "architect")
    assert order_counter.count == 1  # precedence order fetched exactly once, not per candidate


@pytest.mark.asyncio
async def test_resolve_precedence_repeated_call_reuses_warm_cache_auth07_ac07(
    migrated_db: AlembicRunner,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """AUTH-07-AC-7 regression: `GET /api/me` called repeatedly for the same
    session while the 300s cache is warm must issue NO additional
    Tier-1/2/3 lookup. `resolve_precedence` previously bypassed
    `PersonaResolver`'s per-role cache entirely (`_lookup_tiers` called
    directly, `_cached_lookup` did not exist) -- a SECOND call for the
    exact same candidate roles re-ran the full Tier-3 fallthrough for
    every surviving role, live Postgres SELECT included. This is the
    missing repeated-call coverage the validation + review findings both
    named: a single-call query bound (see the test directly above) does
    NOT prove a repeated call is cheap.

    Both candidate roles resolve to a REAL persona here (unlike the test
    above, whose "qa" is a permanent miss) -- AC-26 forbids caching a
    miss, so a role that never maps to anything is re-queried on every
    call by design and would not isolate the warm-cache guarantee this
    test exists to prove. Two calls to `resolve_precedence` for the
    identical `["qa", "architect"]` candidate set -- both now mapped --
    sharing one query-counting context, must produce the SAME totals a
    single cold call does (role_counter == 2, order_counter == 1) -- i.e.
    the second call contributes ZERO additional Tier-3 queries of either
    kind."""
    await test_session.execute(
        sa.insert(PersonaConfig).values(role="architect", persona="architect")
    )
    await test_session.execute(sa.insert(PersonaConfig).values(role="qa", persona="developer"))
    await test_session.commit()

    tier2_path = _write_tier2_yaml(tmp_path, {})  # "qa" and "architect" both miss Tier-1/2
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    resolver = persona_resolver.PersonaResolver(
        settings, session_factory=async_sessionmaker(bind=test_engine, expire_on_commit=False)
    )

    with (
        _count_persona_config_selects(test_engine) as role_counter,
        _count_persona_precedence_selects(test_engine) as order_counter,
    ):
        first_winner = await resolver.resolve_precedence(["qa", "architect"])
        second_winner = await resolver.resolve_precedence(["qa", "architect"])  # warm cache

    # "architect" outranks "developer" in the default precedence order.
    assert first_winner == second_winner == "architect"
    # Same totals as the single-call bound above -- the second call added
    # NOTHING: not a role-tier SELECT, not a precedence-order SELECT.
    assert role_counter.count == 2  # NOT 4 -- warm cache, no re-query on the 2nd call
    assert order_counter.count == 1  # NOT 2 -- precedence order stayed warm too


# -----------------------------------------------------------------------------
# AUTH-07-AC-25/AC-26/FR-8 (T-05) -- `persona_mapping_not_found` event, D-04.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persona_mapping_not_found_emitted_before_raise_on_single_role_miss_auth07_tc02(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    """AUTH-07-TC-02 (docs/test-cases/AUTH-07.json) -- D-04(a): the
    single-role `resolve()` path (via `_resolve_uncached`'s own
    all-3-tier-miss) emits `persona_mapping_not_found` before raising
    `PersonaNotFoundError` (fail-closed unchanged). Uses the direct-attach
    `_RecordCapturingHandler` idiom -- never `caplog`/`capsys`, which pass
    vacuously after any `migrated_db` test under Alembic's
    `fileConfig(disable_existing_loggers=True)` sweep."""
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(persona=None)  # Tier-3 miss too
    resolver = _pure_mock_resolver(settings, session_factory)

    with pytest.raises(persona_resolver.PersonaNotFoundError):
        await resolver.resolve("nonexistent-role")

    not_found = _not_found_events(persona_logger_records)
    assert len(not_found) == 1
    assert not_found[0].roles == ["nonexistent-role"]  # type: ignore[attr-defined]
    assert not_found[0].tiers_consulted == [  # type: ignore[attr-defined]
        "tier-1-env",
        "tier-2-yaml",
        "tier-3-postgres",
    ]
    # `LogRecord.name` is the LOGGER's own name (e.g. "app.core.persona_resolver"),
    # a stdlib builtin attribute unrelated to this payload -- only check the
    # genuine `extra` keys a PII leak would actually be injected through.
    for field in ("user_id", "email", "groups"):
        assert not hasattr(not_found[0], field)
    assert not_found[0].name == "app.core.persona_resolver"
    # Grep-distinguishable from a successful resolution -- the event NAME
    # alone is sufficient (AC-25); no persona_mapping_loaded fired either.
    assert _mapping_events(persona_logger_records) == []


@pytest.mark.asyncio
async def test_resolve_precedence_all_candidates_miss_emits_one_aggregated_not_found_event(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    """D-04(b): the multi-role path aggregates every surviving role
    attempted into ONE `persona_mapping_not_found` event when none of them
    produce a persona -- never one event per losing candidate."""
    tier2_path = _write_tier2_yaml(tmp_path, {})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(persona=None)
    resolver = _pure_mock_resolver(settings, session_factory)

    with pytest.raises(persona_resolver.PersonaNotFoundError):
        await resolver.resolve_precedence(["qa", "nonexistent-2"])

    not_found = _not_found_events(persona_logger_records)
    assert len(not_found) == 1
    assert not_found[0].roles == ["qa", "nonexistent-2"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_resolve_precedence_one_surviving_candidate_never_logs_not_found(
    tmp_path: Path, persona_logger_records: list[logging.LogRecord]
) -> None:
    """D-04's whole rationale for a dedicated multi-role emission point: a
    token carrying one persona role (`architect`) plus an unrelated,
    genuinely-unmapped business role (`qa`) must NOT spuriously log
    `persona_mapping_not_found` for `qa` -- only an ALL-candidates miss
    logs anything."""
    tier2_path = _write_tier2_yaml(tmp_path, {"architect": "architect"})
    settings = _build_settings(tier1_map=None, persona_config_file=tier2_path)
    session_factory = FakeSessionFactory(persona=None)  # "qa" misses Tier-3 too
    resolver = _pure_mock_resolver(settings, session_factory)

    winner = await resolver.resolve_precedence(["qa", "architect"])

    assert winner == "architect"
    assert _not_found_events(persona_logger_records) == []
