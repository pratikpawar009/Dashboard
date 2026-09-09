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
- BED-05-AC-3: neither rollup-rebuild call site (`app/api/ingest.py`,
  `app/services/manifest_ingest.py`) moved a single byte across this story's
  whole diff — asserted against the real git blob at the commit BED-05
  branched from, not an import-only smoke check — and `DECISIONS.md` records
  D-05's caller-ordering write-up `ING-02` must implement.

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
import re
import subprocess
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
# parents[3] = services, parents[4] = repo root -- needed for the AC-3 git-blob
# diff and DECISIONS.md below.
REPO_ROOT = Path(__file__).resolve().parents[4]
DECISIONS_MD_PATH = REPO_ROOT / "docs" / "features" / "BED-05" / "DECISIONS.md"

# BED-03-TC-16 test_data.forbidden_log_fields, copied verbatim.
FORBIDDEN_LOG_FIELDS = ("email", "user_email", "raw_content", "prompt_text")

# BED-05-AC-3: the two rollup-rebuild call sites this story must never edit,
# repo-root-relative (the shape `git show <ref>:<path>` needs).
AC3_FROZEN_CALL_SITES = (
    "services/api/app/api/ingest.py",
    "services/api/app/services/manifest_ingest.py",
)


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


# ---------------------------------------------------------------------------
# BED-05-AC-3 — call-site regression + DECISIONS.md write-up
# ---------------------------------------------------------------------------


def _resolve_ac3_diff_base_ref() -> str:
    """The commit BED-05 branched from — the merge-base between `HEAD` and
    `main` — so the byte-identical check below measures THIS story's own
    diff contribution, not `main`'s current tip (which can move for reasons
    unrelated to BED-05 and would otherwise produce a false failure/pass).
    Tries `origin/main` first (the ref a fresh clone actually has), then a
    local `main` branch; skips (not xfail/pass) if neither resolves, since a
    checkout without either ref genuinely cannot answer this question.
    """
    for candidate in ("origin/main", "main"):
        result = subprocess.run(
            ["git", "merge-base", "HEAD", candidate],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    pytest.skip(
        "neither origin/main nor main resolves in this checkout — cannot compute "
        "the AC-3 diff-base commit"
    )


def _git_blob_bytes(ref: str, repo_relative_path: str) -> bytes:
    """Raw bytes of `repo_relative_path` as committed at `ref` (no `text=True`
    decoding — AC-3 is a byte-identical check, not a text-normalized one).
    """
    result = subprocess.run(
        ["git", "show", f"{ref}:{repo_relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"git show {ref}:{repo_relative_path} failed: "
        f"{result.stderr.decode(errors='replace')}"
    )
    return result.stdout


@pytest.mark.parametrize("repo_relative_path", AC3_FROZEN_CALL_SITES)
def test_ac3_call_site_is_byte_identical_to_pre_bed_05_commit(repo_relative_path: str) -> None:
    """AC-3: this whole feature's diff touches neither call site. Asserted by
    diffing the CURRENT working-tree file, byte for byte, against the git
    blob at the commit BED-05 branched from — a real diff check against
    history, not an import-only smoke test that would pass whether or not
    either file changed. A mismatch means this feature edited a file it must
    never touch; only `ING-02` may change either caller (D-05).
    """
    base_ref = _resolve_ac3_diff_base_ref()
    baseline = _git_blob_bytes(base_ref, repo_relative_path)
    current = (REPO_ROOT / repo_relative_path).read_bytes()
    assert current == baseline, (
        f"{repo_relative_path} differs from its content at {base_ref} — AC-3 forbids "
        "BED-05 from editing either rollup-rebuild call site"
    )


def test_decisions_md_records_the_d05_caller_ordering_write_up() -> None:
    """AC-3 requires the `ING-02` caller-ordering write-up to be recorded in
    this module's own `DECISIONS.md`, not implemented here (D-05). Scopes
    every assertion to the D-05 section specifically (not the whole file) so
    an unrelated decision mentioning the same terms can't produce a false
    pass.
    """
    text = DECISIONS_MD_PATH.read_text()
    match = re.search(r"### D-05:.*?(?=\n### D-\d|\Z)", text, re.DOTALL)
    assert match, "DECISIONS.md has no D-05 entry"
    section = match.group(0)

    assert "ING-02" in section, "D-05 must name ING-02 as the caller-ordering owner"
    assert "rebuild_program_rollups" in section
    assert "rebuild_org_rollups" in section
    for repo_relative_path in AC3_FROZEN_CALL_SITES:
        file_name = Path(repo_relative_path).name
        assert file_name in section, f"D-05 does not name {file_name} as a frozen call site"
