"""`app.services.rollup_rebuild` — module contract + security (BED-03-TC-09,
BED-03-TC-16).

Covers:
- TC-09 (FR-1): `rebuild_program_rollups`/`rebuild_org_rollups` carry the
  documented async signatures (`session: AsyncSession` + `program_id: str`
  for the program variant), a real call against a seeded test DB returns a
  `RebuildResult` exposing exactly `{scope, program_id, duration_ms,
  event_count}` (D-06 — frozen dataclass), and neither function constructs
  its own session/engine. The "no self-constructed session" check parses
  `rollup_rebuild.py` with `ast` rather than a raw text scan, so it isn't
  fooled by the string appearing in a docstring/comment (the module's own
  docstring mentions `SessionLocal`), and asserts on the two *public*
  functions' call graphs specifically, not the private `_rebuild_transaction`
  helper.
- TC-16 (NFR-security): no route in `app.main`'s router table resolves to
  either rebuild function, no `app/api/*.py` router module references them by
  name, and a real end-to-end rebuild call's captured log output (via the
  actual `app.core.logging.JSONFormatter` seam, matching `test_logging.py`'s
  idiom) never carries a PII field, per `.claude/rules/security-baseline.md`.

Against the disposable test database via `migrated_db`/`test_session`
(`tests/conftest.py`), matching `tests/unit/test_rollup_rebuild_program.py`'s
established live-DB seeding pattern.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import app.models as models
import app.services.rollup_rebuild as rollup_rebuild_module
from app.core.logging import JSONFormatter
from app.services.rollup_rebuild import (
    RebuildResult,
    rebuild_org_rollups,
    rebuild_program_rollups,
)
from tests.conftest import AlembicRunner

# services/api/tests/unit/test_rollup_rebuild_contract.py -> parents[2] = services/api
API_ROOT = Path(__file__).resolve().parents[2]
API_ROUTERS_DIR = API_ROOT / "app" / "api"

# BED-03-TC-16 test_data.forbidden_log_fields, copied verbatim.
FORBIDDEN_LOG_FIELDS = ("email", "user_email", "raw_content", "prompt_text")


def _usage_event_row(**overrides: Any) -> dict[str, Any]:
    """One `usage_events` row dict with required-field defaults, matching
    `tests/unit/test_rollup_rebuild_program.py::_usage_event_row`'s shape.
    """
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "program_id": "prog-x",
        "ts": datetime.now(UTC),
        "cmd_ts": datetime.now(UTC),
        "user": "test-user",
        "session_id": "sess-abc",
        "command": "test-command",
        "duration_seconds": 1,
        "outcome": "success",
        "total": 100,
    }
    row.update(overrides)
    return row


async def _insert_events(test_session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    await test_session.execute(sa.insert(models.UsageEvent), rows)
    await test_session.commit()


class _RecordCapturingHandler(logging.Handler):
    """Stores emitted LogRecord instances verbatim, without formatting them
    (matches `tests/unit/test_logging.py::_RecordCapturingHandler`).
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _calls_in(node: ast.AST) -> set[str]:
    """Every function/method name invoked anywhere inside `node`."""
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


# ---------------------------------------------------------------------------
# BED-03-TC-09 — signatures, RebuildResult shape, no self-constructed session
# ---------------------------------------------------------------------------


def test_signatures_match_documented_contract() -> None:
    """Both functions are coroutine functions with the documented params."""
    assert inspect.iscoroutinefunction(rebuild_program_rollups)
    program_sig = inspect.signature(rebuild_program_rollups)
    assert list(program_sig.parameters) == ["session", "program_id"]
    assert program_sig.parameters["session"].annotation is AsyncSession
    assert program_sig.parameters["program_id"].annotation is str
    assert program_sig.return_annotation is RebuildResult

    assert inspect.iscoroutinefunction(rebuild_org_rollups)
    org_sig = inspect.signature(rebuild_org_rollups)
    assert list(org_sig.parameters) == ["session"]
    assert org_sig.parameters["session"].annotation is AsyncSession
    assert org_sig.return_annotation is RebuildResult


def test_rebuild_result_dataclass_exposes_exactly_the_documented_fields() -> None:
    """`dataclasses.fields` — neither missing a field nor carrying an extra."""
    expected = {"scope", "program_id", "duration_ms", "event_count"}
    actual = {field.name for field in dataclasses.fields(RebuildResult)}
    assert actual == expected


@pytest.mark.asyncio
async def test_rebuild_program_rollups_call_returns_documented_result_shape(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """A real call against a seeded test DB inspects the returned object."""
    program_id = "prog-x"
    await _insert_events(test_session, [_usage_event_row(program_id=program_id)])

    result = await rebuild_program_rollups(test_session, program_id)

    assert {field.name for field in dataclasses.fields(result)} == {
        "scope",
        "program_id",
        "duration_ms",
        "event_count",
    }
    assert result.scope == "program"
    assert result.program_id == program_id
    assert isinstance(result.duration_ms, int)
    assert isinstance(result.event_count, int)
    assert result.event_count == 1


def test_public_functions_never_construct_their_own_session_or_engine() -> None:
    """AST-based check (robust against the string appearing in a docstring):
    walk only the two public async function bodies and assert neither calls
    `SessionLocal()` or `create_async_engine()`.
    """
    source = inspect.getsource(rollup_rebuild_module)
    tree = ast.parse(source)
    target_names = {"rebuild_program_rollups", "rebuild_org_rollups"}
    forbidden_calls = {"SessionLocal", "create_async_engine"}
    checked: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in target_names:
            checked.add(node.name)
            offending = _calls_in(node) & forbidden_calls
            assert not offending, (
                f"{node.name} calls {offending} — must use only the injected session"
            )

    assert checked == target_names, "expected to find both public rebuild functions to check"


# ---------------------------------------------------------------------------
# BED-03-TC-16 — no PII in logs, no HTTP route
# ---------------------------------------------------------------------------


def test_no_api_router_module_references_either_rebuild_function() -> None:
    forbidden_names = ("rebuild_program_rollups", "rebuild_org_rollups")
    for path in sorted(API_ROUTERS_DIR.glob("*.py")):
        text = path.read_text()
        for name in forbidden_names:
            assert name not in text, f"{path} references {name} — no route may exist yet"


def test_no_route_resolves_to_either_rebuild_function() -> None:
    from app.main import app as fastapi_app

    forbidden = {rebuild_program_rollups, rebuild_org_rollups}
    endpoints = {getattr(route, "endpoint", None) for route in fastapi_app.routes}
    assert not (endpoints & forbidden)


@pytest.mark.asyncio
async def test_rebuild_calls_log_no_pii_fields(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """Real rebuild calls, real logger, real `JSONFormatter` — no PII field
    (BED-03-TC-16 test_data.forbidden_log_fields) appears in the captured
    output, per `.claude/rules/security-baseline.md`.
    """
    program_id = "prog-log-security-1"
    await _insert_events(
        test_session,
        [
            _usage_event_row(program_id=program_id, session_id="sess-sec-1"),
            _usage_event_row(program_id="prog-log-security-2", session_id="sess-sec-2"),
        ],
    )

    # `migrated_db` runs Alembic, and `migrations/env.py:19` calls
    # `logging.config.fileConfig` with the stdlib default
    # `disable_existing_loggers=True`, which sets `.disabled = True` on every
    # logger that already exists at that point and isn't named in the
    # fileConfig — including this one, created at module-import time —
    # for the rest of the process (AF-08-carry, BED-01, deferred). A
    # disabled logger drops every `logger.info(...)` call as a no-op before a
    # LogRecord is even built. Forcing `.disabled = False` here (matching
    # `tests/unit/test_range_validation.py::_isolated_range_logger`'s
    # established workaround) makes the capture immune to that.
    logger = logging.getLogger(rollup_rebuild_module.__name__)
    previous_disabled = logger.disabled
    previous_propagate = logger.propagate
    previous_level = logger.level
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = _RecordCapturingHandler()
    logger.addHandler(handler)
    try:
        await rebuild_program_rollups(test_session, program_id)
        await rebuild_org_rollups(test_session)
    finally:
        logger.removeHandler(handler)
        logger.disabled = previous_disabled
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate

    assert handler.records, "expected rollup_rebuild_completed log lines to be captured"

    formatter = JSONFormatter()
    for record in handler.records:
        formatted = formatter.format(record)
        payload = json.loads(formatted)  # must be well-formed JSON
        serialized = json.dumps(payload)
        for field in FORBIDDEN_LOG_FIELDS:
            assert field not in serialized, f"forbidden field {field!r} found in: {formatted}"
