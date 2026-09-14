"""Router smoke for the generic `POST /api/ingest/{kind}` (ING-03 T-11 /
F-17; ADR-0013 audit surface).

Traces:

- **ING-03-AC-1 / AC-4** -- generic route is a SINGLE handler at
  `/api/ingest/{kind}`, not two separate `/files`+`/artifacts` entries.
  A future PR that re-forks the router by re-adding a second
  `@router.post(...)` would show up as two path entries here.
- **ING-03-FR-1** -- envelope-kind check runs BEFORE bearer auth. An
  unknown-kind request must never reach `get_ingest_token`. Mocked
  `get_ingest_token` is asserted un-invoked on the reject path.
- **D-03 / ADR-0012 non-applicability router-tier guard** -- the
  artifacts branch does NOT call `background_tasks.add_task(...)`.

Scope: this file mocks BOTH service dispatches to sentinels so the
router is exercised in isolation. Real-DB behaviour is out of scope
(T-07 / T-08 cover it against a live Postgres). No log-capture idiom
here (F-15 / F-18 own that).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import ingest as ingest_router_module
from app.core.db import get_db
from app.models.ingestion import IngestToken
from app.schemas.ingest_artifacts import IngestArtifactsResponse
from app.schemas.ingest_files import IngestFilesResponse

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


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


def _fake_token() -> IngestToken:
    tok = IngestToken()
    tok.label = "test-token"
    tok.allowed_program_ids = ["prog-generic"]
    return tok


def test_only_one_generic_route_is_registered(
    build_app: Callable[..., FastAPI],
) -> None:
    """AC-1 / AC-4: the ingest router mounts exactly one handler at
    `/api/ingest/{kind}` -- not two (or three) separate literal-path
    entries. `/api/ingest/manifest` is a sibling router owned by
    `app/api/manifest.py` and does not count against this budget."""
    app = build_app()
    ingest_paths = [
        getattr(route, "path", None) for route in app.routes
    ]
    generic_hits = [p for p in ingest_paths if p == "/api/ingest/{kind}"]
    assert generic_hits == ["/api/ingest/{kind}"], (
        f"expected exactly one /api/ingest/{{kind}} handler, "
        f"got {generic_hits}"
    )
    assert "/api/ingest/files" not in ingest_paths, (
        "the retired `/api/ingest/files` literal URL must not be registered"
    )
    assert "/api/ingest/artifacts" not in ingest_paths, (
        "artifacts must be handled by the `/api/ingest/{kind}` path-param, "
        "not a literal `/artifacts` route"
    )


@pytest.mark.asyncio
async def test_unknown_kind_returns_400_before_auth(
    build_app: Callable[..., FastAPI],
    test_session: AsyncSession,
    async_client_for: AsyncClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-1: envelope-kind reject fires BEFORE `get_ingest_token`. Any
    other order lets an anonymous caller probe the auth response space
    via kind-guessing."""
    app = _build_ingest_app(build_app, test_session)
    get_token_mock = AsyncMock(return_value=_fake_token())
    monkeypatch.setattr(ingest_router_module, "get_ingest_token", get_token_mock)

    async with async_client_for(app) as client:
        resp = await client.post(
            "/api/ingest/unknown_kind",
            json={"program_id": "prog-any", "kind": "unknown_kind"},
            headers={"Authorization": "Bearer irrelevant"},
        )

    assert resp.status_code == 400
    get_token_mock.assert_not_called()


@pytest.mark.asyncio
async def test_activity_kind_reaches_activity_dispatch(
    build_app: Callable[..., FastAPI],
    test_session: AsyncSession,
    async_client_for: AsyncClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0013 dispatch: URL kind='activity' reaches
    `activity_ingest.ingest_files(...)`, not `ingest_artifacts(...)`."""
    app = _build_ingest_app(build_app, test_session)
    monkeypatch.setattr(
        ingest_router_module, "get_ingest_token", AsyncMock(return_value=_fake_token())
    )
    activity_sentinel = IngestFilesResponse(received=0, valid=0, inserted=0, updated=0)
    activity_mock = AsyncMock(return_value=activity_sentinel)
    monkeypatch.setattr(ingest_router_module, "ingest_files", activity_mock)
    artifacts_mock = AsyncMock()
    monkeypatch.setattr(ingest_router_module, "ingest_artifacts", artifacts_mock)

    async with async_client_for(app) as client:
        resp = await client.post(
            "/api/ingest/activity",
            json={"program_id": "prog-generic", "kind": "activity", "rows": []},
            headers={"Authorization": "Bearer irrelevant"},
        )

    assert resp.status_code == 200
    activity_mock.assert_awaited_once()
    artifacts_mock.assert_not_called()


@pytest.mark.asyncio
async def test_artifacts_kind_reaches_artifacts_dispatch(
    build_app: Callable[..., FastAPI],
    test_session: AsyncSession,
    async_client_for: AsyncClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0013 dispatch: URL kind='artifacts' reaches
    `ingest_artifacts(...)`, not `activity_ingest.ingest_files(...)`."""
    app = _build_ingest_app(build_app, test_session)
    monkeypatch.setattr(
        ingest_router_module, "get_ingest_token", AsyncMock(return_value=_fake_token())
    )
    activity_mock = AsyncMock()
    monkeypatch.setattr(ingest_router_module, "ingest_files", activity_mock)
    artifacts_sentinel = IngestArtifactsResponse(rows_received=1, rows_upserted=1)
    artifacts_mock = AsyncMock(return_value=artifacts_sentinel)
    monkeypatch.setattr(ingest_router_module, "ingest_artifacts", artifacts_mock)

    body = {
        "program_id": "prog-generic",
        "kind": "artifacts",
        "counts": {"prd": 3},
        "as_of": datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC).isoformat(),
    }
    async with async_client_for(app) as client:
        resp = await client.post(
            "/api/ingest/artifacts",
            json=body,
            headers={"Authorization": "Bearer irrelevant"},
        )

    assert resp.status_code == 200
    artifacts_mock.assert_awaited_once()
    activity_mock.assert_not_called()


@pytest.mark.asyncio
async def test_artifacts_branch_never_schedules_background_task(
    build_app: Callable[..., FastAPI],
    test_session: AsyncSession,
    async_client_for: AsyncClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-03 / ADR-0012 router-tier guard: the artifacts dispatch branch
    MUST NOT call `background_tasks.add_task(...)`. Spy on the
    `BackgroundTasks` class's `add_task` and assert un-invoked on the
    artifacts path."""
    app = _build_ingest_app(build_app, test_session)
    monkeypatch.setattr(
        ingest_router_module, "get_ingest_token", AsyncMock(return_value=_fake_token())
    )
    monkeypatch.setattr(
        ingest_router_module,
        "ingest_artifacts",
        AsyncMock(return_value=IngestArtifactsResponse(rows_received=1, rows_upserted=1)),
    )
    add_task_spy = MagicMock()

    def _spy_add_task(self: Any, *args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        add_task_spy(*args, **kwargs)

    monkeypatch.setattr(
        "fastapi.background.BackgroundTasks.add_task", _spy_add_task, raising=False
    )

    body = {
        "program_id": "prog-generic",
        "kind": "artifacts",
        "counts": {"prd": 3},
        "as_of": datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC).isoformat(),
    }
    async with async_client_for(app) as client:
        resp = await client.post(
            "/api/ingest/artifacts",
            json=body,
            headers={"Authorization": "Bearer irrelevant"},
        )

    assert resp.status_code == 200
    add_task_spy.assert_not_called()
