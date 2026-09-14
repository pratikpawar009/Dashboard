"""ING-03-TC-02 -- auth/authz denial matrix for
`POST /api/ingest/artifacts` (T-08 / F-14).

Mirrors `test_ingest_files_auth_denial.py` (ING-02 T-14): a real-DB
denial matrix using `migrated_db` + `test_session` + a real ASGI
`create_app()` via `build_app`/`async_client_for`. `get_db` is
overridden to `test_session` so token seeding, the HTTP request, and
post-request row-count queries share one connection.

Coverage per ING-03 TC-02 / AC-2 / AC-4 / FR-1:

- No bearer -> 401 "missing"
- Valid-shape unknown token -> 401 "unknown"
- Valid token whose `allowed_program_ids` excludes the envelope's
  `program_id` -> 403 "scope"
- Valid token + unknown canonical type in `counts` -> 400
  (`ArtifactCountsIn` validator raises `unknown_canonical_type`)
- Envelope-kind (URL path + body) reject BEFORE auth -- no header,
  unknown kind -> 400 (not 401)

Post-condition (integration-level): `SELECT COUNT(*) FROM
program_artifacts WHERE program_id IN ('prog-scoped-ing03',
'prog-other-ing03')` MUST be 0 after every denial path -- no partial
write ever escapes into `program_artifacts` from a rejected request.

D-03 guard (integration-tier): the artifacts branch MUST NOT call
`background_tasks.add_task(...)`. Spy on `BackgroundTasks.add_task`
in every denial and the unknown-type reject: it must never fire.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.governance import ProgramArtifact
from app.models.ingestion import IngestToken
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

_INGEST_ARTIFACTS_PATH = "/api/ingest/artifacts"
_SCOPED_PROGRAM = "prog-scoped-ing03"
_OTHER_PROGRAM = "prog-other-ing03"
_AS_OF_ISO = "2026-09-13T10:00:00Z"


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_ingest_app(
    build_app: Callable[..., FastAPI], test_session: AsyncSession
) -> FastAPI:
    app = build_app()
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


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
        user_email="ingest-owner@example.invalid",
        allowed_program_ids=allowed_program_ids,
    )
    test_session.add(row)
    await test_session.commit()
    return raw_token


def _envelope(
    *,
    program_id: str = _SCOPED_PROGRAM,
    kind: str = "artifacts",
    counts: dict[str, int] | None = None,
    as_of: str = _AS_OF_ISO,
) -> dict[str, Any]:
    return {
        "program_id": program_id,
        "kind": kind,
        "counts": counts if counts is not None else {"prd": 3, "test_case": 12},
        "as_of": as_of,
    }


async def _post(
    async_client_for: AsyncClientFactory,
    app: FastAPI,
    *,
    payload: Any,
    token: str | None = None,
    url: str = _INGEST_ARTIFACTS_PATH,
) -> Response:
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    async with async_client_for(app) as client:
        return await client.post(url, json=payload, headers=headers)


async def _count_artifacts(session: AsyncSession) -> int:
    """Rows in `program_artifacts` scoped to the two program ids under
    test in this file. Any non-zero value after a denial path is a hard
    fail per TC-02 / AC-2 / AC-4 post-conditions."""
    result = await session.execute(
        sa.select(sa.func.count())
        .select_from(ProgramArtifact)
        .where(ProgramArtifact.program_id.in_([_SCOPED_PROGRAM, _OTHER_PROGRAM]))
    )
    return int(result.scalar_one())


@pytest.fixture(autouse=True)
def _spy_background_tasks(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """D-03 integration-tier guard: every test in this file asserts
    that the artifacts branch NEVER schedules a background task, on
    every path (denial or reject)."""
    spy = MagicMock()

    def _spy_add_task(self: Any, *args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        spy(*args, **kwargs)

    monkeypatch.setattr(
        "fastapi.background.BackgroundTasks.add_task", _spy_add_task, raising=False
    )
    return spy


@pytest.mark.asyncio
async def test_no_bearer_returns_401_missing(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    _spy_background_tasks: MagicMock,
) -> None:
    """AC-2: absent `Authorization` header returns 401."""
    app = _build_ingest_app(build_app, test_session)
    resp = await _post(async_client_for, app, payload=_envelope(), token=None)
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["message"] == "missing"
    assert await _count_artifacts(test_session) == 0
    _spy_background_tasks.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_token_returns_401_unknown(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    _spy_background_tasks: MagicMock,
) -> None:
    """AC-2: well-shaped but never-minted token returns 401."""
    app = _build_ingest_app(build_app, test_session)
    never_minted = "hrn_pat_" + secrets.token_hex(32)
    resp = await _post(async_client_for, app, payload=_envelope(), token=never_minted)
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["message"] == "unknown"
    assert await _count_artifacts(test_session) == 0
    _spy_background_tasks.assert_not_called()


@pytest.mark.asyncio
async def test_wrong_program_scope_returns_403_scope(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    _spy_background_tasks: MagicMock,
) -> None:
    """AC-2 / ADR-0006 §3: valid token whose `allowed_program_ids`
    excludes the envelope `program_id` (and no `*` wildcard) returns
    403."""
    other_scope_token = await _seed_token(
        test_session,
        label="ing03-tc02-wrong-scope",
        allowed_program_ids=[_OTHER_PROGRAM],
    )
    app = _build_ingest_app(build_app, test_session)
    resp = await _post(
        async_client_for,
        app,
        payload=_envelope(program_id=_SCOPED_PROGRAM),
        token=other_scope_token,
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["message"] == "scope"
    assert await _count_artifacts(test_session) == 0
    _spy_background_tasks.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_canonical_type_returns_400(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    _spy_background_tasks: MagicMock,
) -> None:
    """AC-4 / FR-2: `counts` key outside the closed canonical vocabulary
    (`prd/user_story/test_case/arch_diagram/api_spec`) is rejected 400
    at the schema tier, before any DB write. Token is valid to prove
    the reject fires on its own dimension, not as a downstream
    consequence of auth."""
    token = await _seed_token(
        test_session,
        label="ing03-tc02-bad-type",
        allowed_program_ids=[_SCOPED_PROGRAM],
    )
    app = _build_ingest_app(build_app, test_session)
    resp = await _post(
        async_client_for,
        app,
        payload=_envelope(counts={"design_doc": 5}),
        token=token,
    )
    assert resp.status_code == 400, resp.text
    assert await _count_artifacts(test_session) == 0
    _spy_background_tasks.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_kind_before_auth_returns_400(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    _spy_background_tasks: MagicMock,
) -> None:
    """FR-1: envelope-kind reject runs BEFORE bearer auth. NO
    `Authorization` header AND URL kind not in `_ACCEPTED_KINDS` -->
    400 (not 401). This is the identical ordering contract ING-02 T-14
    Test 8 pinned for the activity branch, generalised here to the
    unknown-kind path."""
    app = _build_ingest_app(build_app, test_session)
    resp = await _post(
        async_client_for,
        app,
        payload={"program_id": _SCOPED_PROGRAM, "kind": "unknown_kind"},
        token=None,
        url="/api/ingest/unknown_kind",
    )
    assert resp.status_code == 400, resp.text
    assert await _count_artifacts(test_session) == 0
    _spy_background_tasks.assert_not_called()
