"""ING-03-TC-01 -- artifacts idempotency happy path (T-07 / F-13).

Real-DB integration test for `POST /api/ingest/artifacts`. Same
scaffolding shape as `test_ingest_files_idempotency.py` (ING-02 T-13):

- `migrated_db` runs Alembic once; every test in this file shares one
  disposable Postgres schema.
- `_db_override(test_session)` dependency-overrides `get_db` so the
  seeded token + the POST + the post-verification queries all share one
  live connection.
- `_seed_ingest_token` mirrors `test_ingest_files_idempotency.py`'s
  helper verbatim (per this repo's per-file test-helper convention),
  scoped to the `artifacts` scope constant so ADR-0006 scope-semantics
  survive an integration probe.

TC-01 scope (`docs/test-cases/ING-03.json`):

  Pre-seed `(prog-ing03-a, user_story, 7, 2026-09-01T00:00:00Z)`. POST
  `{prd: 3, test_case: 12}` twice with `as_of=2026-09-13T10:00:00Z`.
  Each POST returns 200 with `rows_upserted=2`. Post-state has exactly
  three rows: `(prd, 3)`, `(test_case, 12)`, `(user_story, 7)` -- the
  pre-seeded `user_story` row is unchanged.

D-03 guard (integration-tier): the artifacts branch MUST NOT schedule
`dispatch_org_rebuild` as a `BackgroundTasks.add_task`. This test does
NOT stub `dispatch_org_rebuild` -- if the artifacts branch accidentally
scheduled it, the test would hit a real DB rebuild path against the
disposable test DB and fail in a very different way. Better: assert
`BackgroundTasks.add_task` was never called.

Scope of what this file covers, in one sentence: it is the ONE test
proving the artifacts upsert produces the exact 3-row post-state on
idempotent re-POST -- the schema layer (F-12), router layer (F-17),
service allowlist (F-15/F-18), and static D-03 guard (F-16) each cover
a slice, but only the real DB proves the on-conflict-do-update behaves
as ADR-0013 promises against a live Postgres.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.governance import ProgramArtifact
from app.models.ingestion import IngestToken
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

_INGEST_ARTIFACTS_PATH = "/api/ingest/artifacts"
_PROGRAM_ID = "prog-ing03-a"
_AS_OF_ISO = "2026-09-13T10:00:00Z"
_AS_OF = datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC)


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


async def _seed_ingest_token(
    test_session: AsyncSession, *, label: str, allowed_program_ids: list[str]
) -> str:
    """Seed one `ingest_tokens` row and return its raw (pre-hash) token."""
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


async def _seed_program_artifact(
    test_session: AsyncSession,
    *,
    program_id: str,
    artifact_type: str,
    count: int,
    as_of: datetime,
) -> None:
    row = ProgramArtifact(
        program_id=program_id,
        type=artifact_type,
        count=count,
        as_of_timestamp=as_of,
    )
    test_session.add(row)
    await test_session.commit()


async def _fetch_all_artifact_rows(
    session: AsyncSession, program_id: str
) -> list[tuple[str, int, datetime]]:
    result = await session.execute(
        sa.select(
            ProgramArtifact.type,
            ProgramArtifact.count,
            ProgramArtifact.as_of_timestamp,
        )
        .where(ProgramArtifact.program_id == program_id)
        .order_by(ProgramArtifact.type)
    )
    return [(t, c, ts) for t, c, ts in result.all()]


@pytest.mark.asyncio
async def test_ingest_artifacts_idempotent_upsert_happy_path_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-01 (ING-03): pre-seed one row, POST the two-type payload twice
    against a real Postgres, assert exact 3-row post-state and
    idempotency."""
    token = await _seed_ingest_token(
        test_session,
        label="tc01-artifacts-happy",
        allowed_program_ids=[_PROGRAM_ID],
    )

    # Pre-seed the row the payload will NOT touch -- proves the ON
    # CONFLICT scope is `(program_id, type)`, not `(program_id)` (the
    # user_story row's count and as_of stay put).
    pre_seed_as_of = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    await _seed_program_artifact(
        test_session,
        program_id=_PROGRAM_ID,
        artifact_type="user_story",
        count=7,
        as_of=pre_seed_as_of,
    )

    app = _build_ingest_app(build_app, test_session)

    # D-03 integration-tier guard: spy on BackgroundTasks.add_task.
    # The artifacts branch MUST NOT schedule any background work.
    add_task_spy = MagicMock()

    def _spy_add_task(self: Any, *args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        add_task_spy(*args, **kwargs)

    monkeypatch.setattr(
        "fastapi.background.BackgroundTasks.add_task", _spy_add_task, raising=False
    )

    payload = {
        "program_id": _PROGRAM_ID,
        "kind": "artifacts",
        "counts": {"prd": 3, "test_case": 12},
        "as_of": _AS_OF_ISO,
    }
    auth = {"Authorization": f"Bearer {token}"}

    async with async_client_for(app) as client:
        # First POST: two rows inserted (prd, test_case).
        first = await client.post(_INGEST_ARTIFACTS_PATH, json=payload, headers=auth)
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert first_body["rows_received"] == 2
        assert first_body["rows_upserted"] == 2
        assert first_body.get("rejections", []) == []

        # Second POST (identical): two rows re-upserted -- same
        # `rows_upserted=2`. FR-3 / D-02: idempotency delegated to
        # Postgres, so the second call is a well-defined ON CONFLICT
        # DO UPDATE, not a no-op.
        second = await client.post(_INGEST_ARTIFACTS_PATH, json=payload, headers=auth)
        assert second.status_code == 200, second.text
        second_body = second.json()
        assert second_body["rows_received"] == 2
        assert second_body["rows_upserted"] == 2

    # Post-state: exactly 3 rows. `user_story` is unchanged, `prd` and
    # `test_case` reflect the POST values with the new `as_of`.
    rows = await _fetch_all_artifact_rows(test_session, _PROGRAM_ID)
    by_type = {t: (c, ts) for t, c, ts in rows}
    assert set(by_type) == {"prd", "test_case", "user_story"}
    assert by_type["prd"] == (3, _AS_OF)
    assert by_type["test_case"] == (12, _AS_OF)
    # Pre-seeded row untouched (proves ON CONFLICT scope is per-type).
    assert by_type["user_story"] == (7, pre_seed_as_of)

    # D-03: no BackgroundTask was ever scheduled by the artifacts branch.
    add_task_spy.assert_not_called()
