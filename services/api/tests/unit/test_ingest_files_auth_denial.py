"""Auth/authz denial + validation-abort + row-level rejection enumeration for
`POST /api/ingest/files` -- ING-02 T-14 / TC-02 (`docs/test-cases/ING-02.json`,
tracker pratikpawar009/Dashboard#294). Covers AC-2 (401), AC-3 (403),
AC-4 (400 envelope kind + 413 row cap), AC-5 (row-level rejection reason
vocabulary), FR-5 (auth-wiring parity with manifest.py), FR-7 (envelope
kind), and C-7 (rejection body is index+reason only, never row content).

Scope split -- this file owns the *denial matrix* and the *rejection
enumeration*; T-13's `test_ingest_files_idempotency.py` owns the happy
path, T-15's `test_ingest_files_perf.py` owns performance. This file also
does NOT re-test the `get_ingest_token()` denial-branch internals
(revoked/expired/missing/unknown -- already covered by
`tests/unit/test_ingest_token_auth.py`); it verifies that the shipped
router *routes* to those branches, plus the two request-tier aborts and
the row-level rejection vocabulary the service emits.

Uses real Postgres via `migrated_db` + `test_session` and a real ASGI
`create_app()` via `build_app`/`async_client_for` (D-07), mirroring
`test_manifest_auth_scope.py`'s scaffold. `get_db` is overridden to the
disposable `test_session` so token seeding, the HTTP request, and
post-request row-count queries share one connection.

Envelope-check-before-auth ordering (Test 8) -- the router (T-05,
`app/api/ingest_files.py`) documents that `kind` is validated BEFORE
auth to match `api.md#ingest-files-api`'s "Router-tier check, before
auth" ordering. This file's Test 8 pins that with a request that carries
NO Authorization header AND an unknown kind: a 400 (envelope) rather
than a 401 (auth) proves the order stayed intact. If a future refactor
flips the order, that test is what catches it.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.ingestion import IngestToken, UsageEvent
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

_INGEST_FILES_PATH = "/api/ingest/activity"


# -----------------------------------------------------------------------------
# App + DB-override scaffold -- mirrors test_manifest_auth_scope.py.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_ingest_files_app(
    build_app: Callable[..., FastAPI], test_session: AsyncSession
) -> FastAPI:
    app = build_app()
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


# -----------------------------------------------------------------------------
# Token seeding helper -- mirrors test_manifest_auth_scope.py::_seed_token,
# trimmed to the fields this file uses. Raw token is `hrn_pat_` +
# `secrets.token_hex(32)`; only the SHA-256 hash is persisted.
# -----------------------------------------------------------------------------


async def _seed_token(
    test_session: AsyncSession,
    *,
    label: str,
    allowed_program_ids: list[str],
) -> str:
    raw_token = "hrn_pat_" + secrets.token_hex(32)
    row = IngestToken(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        label=label,
        user_email="ingest-owner@example.com",
        allowed_program_ids=allowed_program_ids,
    )
    test_session.add(row)
    await test_session.commit()
    return raw_token


# -----------------------------------------------------------------------------
# Payload builders. `_valid_row` mirrors
# `tests/unit/test_activity_ingest_alias_mapper.py::_minimal_row` -- keep the
# two in sync if `ActivityRowIn`'s required-field set changes.
# -----------------------------------------------------------------------------


def _valid_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "program_id": "P1",
        "ts": "2026-09-11T12:00:00Z",
        "cmd_ts": "2026-09-11T11:59:00Z",
        "user": "u-1",
        "session_id": "S-0001",
        "command": "cmd",
        "duration_s": 3,
        "outcome": "ok",
        "total": 10,
    }
    row.update(overrides)
    return row


def _envelope(
    *,
    program_id: str = "P1",
    kind: str = "activity",
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "program_id": program_id,
        "kind": kind,
        "rows": rows if rows is not None else [_valid_row()],
    }


async def _post(
    async_client_for: AsyncClientFactory,
    app: FastAPI,
    *,
    payload: Any,
    token: str | None = None,
    auth_header: str | None = None,
    raw_body: str | None = None,
) -> Response:
    """POST `_INGEST_FILES_PATH`. `raw_body` sends bytes verbatim (for the
    invalid-JSON test); otherwise `payload` is JSON-encoded normally."""
    if auth_header is not None:
        headers = {"Authorization": auth_header}
    elif token is not None:
        headers = {"Authorization": f"Bearer {token}"}
    else:
        headers = {}
    async with async_client_for(app) as client:
        if raw_body is not None:
            headers["content-type"] = "application/json"
            return await client.post(_INGEST_FILES_PATH, content=raw_body, headers=headers)
        return await client.post(_INGEST_FILES_PATH, json=payload, headers=headers)


async def _usage_events_count(test_session: AsyncSession) -> int:
    result = await test_session.execute(sa.select(sa.func.count()).select_from(UsageEvent))
    return int(result.scalar_one())


# -----------------------------------------------------------------------------
# Test 1 -- AC-2 -- no Authorization header -> 401 "missing".
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_authorization_header_returns_401(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_ingest_files_app(build_app, test_session)

    resp = await _post(async_client_for, app, payload=_envelope(), token=None)

    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["message"] == "missing"
    assert await _usage_events_count(test_session) == 0


# -----------------------------------------------------------------------------
# Test 2 -- AC-2 -- Bearer scheme with a well-formed but never-minted token
# -> 401 "unknown". `get_ingest_token()` only checks hash membership, so a
# properly-shaped garbage token exercises the hash-miss branch cleanly.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_bearer_token_returns_401(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_ingest_files_app(build_app, test_session)
    never_minted = "hrn_pat_" + secrets.token_hex(32)

    resp = await _post(async_client_for, app, payload=_envelope(), token=never_minted)

    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["message"] == "unknown"
    assert await _usage_events_count(test_session) == 0


# -----------------------------------------------------------------------------
# Test 3 -- AC-3 -- valid active token whose `allowed_program_ids` excludes
# the envelope's `program_id` (and carries no "*" wildcard) -> 403 "scope".
# Per ADR-0006 §3 scope semantics + ingest_auth._check_program_scope order.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_program_scope_returns_403(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    other_scope_token = await _seed_token(
        test_session, label="t14-wrong-scope", allowed_program_ids=["OTHER"]
    )
    app = _build_ingest_files_app(build_app, test_session)

    resp = await _post(
        async_client_for, app, payload=_envelope(program_id="P1"), token=other_scope_token
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["message"] == "scope"
    assert await _usage_events_count(test_session) == 0


# -----------------------------------------------------------------------------
# Test 4 -- AC-4 -- unknown envelope kind -> 400 "unknown envelope kind".
# Token is valid to prove the envelope check fires on its own dimension, not
# as a downstream consequence of auth failing.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_envelope_kind_returns_400(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    token = await _seed_token(
        test_session, label="t14-kind-check", allowed_program_ids=["P1"]
    )
    app = _build_ingest_files_app(build_app, test_session)

    resp = await _post(
        async_client_for, app, payload=_envelope(kind="artifacts"), token=token
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["message"] == "unknown envelope kind"
    assert await _usage_events_count(test_session) == 0


# -----------------------------------------------------------------------------
# Test 5 -- request body is not valid JSON -> 400
# "request body is not valid JSON". Router-tier check, fires before auth
# (JSON parse is step 1 in `push_files`'s order per app/api/ingest_files.py).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_json_body_returns_400(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_ingest_files_app(build_app, test_session)

    resp = await _post(async_client_for, app, payload=None, raw_body="{not-json")

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["message"] == "request body is not valid JSON"
    assert await _usage_events_count(test_session) == 0


# -----------------------------------------------------------------------------
# Test 6 -- AC-4 -- rows.length > 5000 with a VALID token -> 413
# "rows exceed the 5000-entry cap". Order note: the router checks the row
# cap AFTER auth (per app/api/ingest_files.py's docstring) so an
# unauthenticated caller cannot use payload size to probe scope; this test
# proves the 413 fires when the batch is oversized and the token is fine.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_row_cap_exceeded_returns_413(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    token = await _seed_token(
        test_session, label="t14-over-cap", allowed_program_ids=["P1"]
    )
    app = _build_ingest_files_app(build_app, test_session)

    over_cap = [_valid_row(session_id=f"S-{i:05d}") for i in range(5001)]
    resp = await _post(
        async_client_for, app, payload=_envelope(rows=over_cap), token=token
    )

    assert resp.status_code == 413, resp.text
    assert resp.json()["error"]["message"] == "rows exceed the 5000-entry cap"
    assert await _usage_events_count(test_session) == 0


# -----------------------------------------------------------------------------
# Row-level rejection enumeration -- one request that triggers each of the
# four rejection reasons AC-5 / FR-3 enumerate. Reason emission order in
# activity_ingest.ingest_files (`app/services/activity_ingest.py`):
#     (1) Pydantic per-row validation errors, in row order
#     (2) row-level program_id_mismatch (only rows that passed Pydantic)
#     (3) intra_batch_duplicate (only rows that passed program-id check)
# So the response's `rejected[]` entries preserve *original* row indices,
# but the entries themselves appear in that reason-precedence order.
#
# Batch layout used by Tests 7 and 9:
#     row 0 -> malformed cmd_ts        -> malformed_iso_date @ index 0
#     row 1 -> missing session_id      -> missing_required_field @ index 1
#     row 2 -> wrong program_id "P9"   -> program_id_mismatch @ index 2
#     row 3 -> valid, session S-A      -> commits
#     row 4 -> valid, session S-B      -> intra_batch_duplicate @ index 4
#                                          (loser -- row 5 wins per last-wins)
#     row 5 -> valid, session S-B      -> commits (last-wins)
# rows_received == 6, rejected == 4, valid == inserted == 2.
# -----------------------------------------------------------------------------


def _mixed_batch() -> list[dict[str, Any]]:
    row_0 = _valid_row(session_id="S-BAD-TS", cmd_ts="not-a-date")

    row_1 = _valid_row(session_id="S-MISSING")
    row_1.pop("session_id")

    row_2 = _valid_row(program_id="P9", session_id="S-SCOPE")

    row_3 = _valid_row(session_id="S-A", cmd_ts="2026-09-11T11:57:00Z")

    duplicate_key_cmd_ts = "2026-09-11T11:58:00Z"
    row_4 = _valid_row(session_id="S-B", cmd_ts=duplicate_key_cmd_ts, total=10)
    row_5 = _valid_row(session_id="S-B", cmd_ts=duplicate_key_cmd_ts, total=99)

    return [row_0, row_1, row_2, row_3, row_4, row_5]


_EXPECTED_MIXED_REJECTIONS = [
    {"index": 0, "reason": "malformed_iso_date"},
    {"index": 1, "reason": "missing_required_field"},
    {"index": 2, "reason": "program_id_mismatch"},
    {"index": 4, "reason": "intra_batch_duplicate"},
]


@pytest.mark.asyncio
async def test_rejection_reason_enumeration_returns_200_with_all_four_reasons(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """Test 7: one request enumerates all four AC-5 row-level rejection reasons
    (`malformed_iso_date`, `missing_required_field`, `program_id_mismatch`,
    `intra_batch_duplicate`). Valid rows in the same batch commit.
    `valid == rows.length - rejected.length` (2 == 6 - 4)."""
    token = await _seed_token(
        test_session, label="t14-mixed-rows", allowed_program_ids=["P1"]
    )
    app = _build_ingest_files_app(build_app, test_session)

    rows = _mixed_batch()
    resp = await _post(async_client_for, app, payload=_envelope(rows=rows), token=token)

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Every AC-5 reason appears exactly once.
    reasons = [entry["reason"] for entry in body["rejected"]]
    assert set(reasons) == {
        "malformed_iso_date",
        "missing_required_field",
        "program_id_mismatch",
        "intra_batch_duplicate",
    }
    assert len(reasons) == 4

    # Indices match reasons per the emission-order comment above.
    assert body["rejected"] == _EXPECTED_MIXED_REJECTIONS

    # AC-1 counters: valid == rows.length - rejected.length; both winners commit.
    assert body["received"] == len(rows) == 6
    assert body["valid"] == len(rows) - len(body["rejected"]) == 2
    assert body["inserted"] == 2
    assert body["updated"] == 0
    assert await _usage_events_count(test_session) == 2


# -----------------------------------------------------------------------------
# Test 8 -- envelope-kind check runs BEFORE auth. Send a bad envelope kind
# with NO Authorization header at all: a 400 (envelope) rather than a 401
# (auth) proves the router-tier order stayed intact per T-05's design note
# in `app/api/ingest_files.py`'s module docstring.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_envelope_kind_check_runs_before_auth(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    app = _build_ingest_files_app(build_app, test_session)

    resp = await _post(
        async_client_for, app, payload=_envelope(kind="artifacts"), token=None
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["message"] == "unknown envelope kind"
    assert await _usage_events_count(test_session) == 0


# -----------------------------------------------------------------------------
# Test 9 -- FR-8 / C-7 -- every `rejected[]` entry has exactly the two
# public keys (`index`, `reason`); no row content, no free-form field leaks
# into the response. Uses the same mixed batch as Test 7 so the assertion
# runs against the full rejection vocabulary.
# -----------------------------------------------------------------------------

_FORBIDDEN_PII_KEYS: frozenset[str] = frozenset(
    {"user", "command", "feature", "session_id", "cmd_ts", "row", "ts", "program_id"}
)


@pytest.mark.asyncio
async def test_rejection_body_carries_index_and_reason_only(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    token = await _seed_token(
        test_session, label="t14-pii-shape", allowed_program_ids=["P1"]
    )
    app = _build_ingest_files_app(build_app, test_session)

    resp = await _post(
        async_client_for, app, payload=_envelope(rows=_mixed_batch()), token=token
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    for entry in body["rejected"]:
        assert set(entry.keys()) == {"index", "reason"}, entry
        assert isinstance(entry["index"], int)
        assert isinstance(entry["reason"], str)
        # None of the forbidden PII/row-content keys must appear anywhere in
        # the entry -- redundant with the set-equality assertion above, but
        # named explicitly per FR-8 / C-7 so a future refactor that adds a
        # `Field` to `RejectionEntry` trips this test loudly.
        assert not (_FORBIDDEN_PII_KEYS & set(entry.keys()))

    # Guard: the response also does not leak row content via some
    # non-`rejected` free-form field. `IngestFilesResponse`'s schema
    # enforces this at the type level, but assert on the wire shape too so
    # a future response-envelope addition trips this test loudly.
    assert set(body.keys()) == {
        "received",
        "valid",
        "inserted",
        "updated",
        "rejected",
        "rollup_summaries",
    }
