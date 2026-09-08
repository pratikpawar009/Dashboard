"""FR-5/AC-8 payload-size cap for `POST /api/ingest/manifest` (T-13, ING-10).
Unbacked by an approved test case -- PLAN.md notes this task closes coverage
the Product Gate's 2-case cap left open.

The cap (`docs/features/ING-10/REQUIREMENTS.md` FR-5, `docs/stories/ING-10.md`
AC-8): `team[]` raw entry count, counted BEFORE alias expansion, greater than
500 -> `413` returned before any row is parsed or written. "Greater than 500"
means exactly 500 is accepted; 501 is the first rejected count -- verified
against both enforcement points' own `_TEAM_ENTRY_CAP = 500` /
`len(raw_team) > _TEAM_ENTRY_CAP` check (`app/api/manifest.py`,
`app/services/manifest_ingest.py`), not assumed.

Two enforcement points, both tested here (AF-09, `docs/features/ING-10/
FLAGS.md`):

- Router (`app/api/manifest.py`) -- checked after auth, before
  `ingest_manifest()` is ever called. This is what a real HTTP client hits,
  so its 413 short-circuits before the service's own cap branch can fire.
- Service (`app/services/manifest_ingest.py`) -- its own internal
  `_TEAM_ENTRY_CAP` check, defence-in-depth for a direct caller (e.g. a future
  MCP/CLI transport bypassing this router entirely).

AF-09 was RESOLVED on 2026-09-08 (triaged `accept`) and this docstring's
earlier claim is now obsolete. It used to read that `ingest_manifest_write` is
"never emitted on the HTTP 413 path" -- true at the time, because the router
short-circuited before the service's own logging branch and an operator saw
nothing for a rejected oversized push. The router now emits the event itself on
that branch, using the SHARED `log_ingest_manifest_write` (promoted from
private for exactly this reason, so FR-2's field allowlist has one
implementation) with values mirroring the service's 413 branch exactly.

So the event IS emitted on the HTTP 413 path, and
`test_over_cap_http_emits_ingest_manifest_write_af09` below asserts it. The
service's own branch remains reachable only by a direct caller.

Pre-alias-expansion counting rule (the subtle part, and the reason a plain
"many rows -> 413" test would encode the wrong rule): the cap counts declared
`team[]` entries, not resulting `program_roster` rows. 400 entries each
carrying 2 aliases expand to 1200 roster rows but stay well under the
500-entry cap, because the cap counts entries, never expanded rows.

HTTP-level tests hit the route through a real, ASGI-transported `create_app()`
instance (`build_app`/`async_client_for`) with a seeded ingest token, mirroring
`test_manifest_auth_scope.py` (T-11) -- including that file's "nothing
written" pattern (`program_roster`/`program_summary`/`user_roles` row counts).
Service-level tests call `app.services.manifest_ingest.ingest_manifest()`
directly against a live, migrated test DB, mirroring
`test_manifest_roster_removal.py` (T-12) -- including that file's
`populate_existing=True` re-fetch guard (AF-14, `docs/features/ING-10/
FLAGS.md`): a raw Core upsert bypasses the ORM identity map, so a session that
already loaded a row can otherwise hand back a stale cached object on re-fetch.

All emails below are synthetic, generated programmatically
(`.claude/rules/security-baseline.md`) -- never hand-typed PII.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.ingestion import IngestToken, UserRole
from app.models.rollup import ProgramSummary
from app.models.roster import ProgramRoster
from app.services.manifest_ingest import ingest_manifest
from tests.conftest import AlembicRunner, repopulate

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

_MANIFEST_PATH = "/api/ingest/manifest"
_TOKEN_LABEL = "test-token"
_CAP = 500  # FR-5/AC-8 -- kept as a local literal, verified against both
# enforcement points' own `_TEAM_ENTRY_CAP` rather than imported, since
# neither module exports the constant (both are private, by design -- see
# app/api/manifest.py's module docstring).


# -----------------------------------------------------------------------------
# Payload builders -- cheap, programmatic, synthetic emails only.
# -----------------------------------------------------------------------------


def _build_team(
    n: int, *, aliases_per_entry: int = 0, email_prefix: str = "member"
) -> list[dict[str, Any]]:
    """`n` synthetic `team[]` entries, each with `aliases_per_entry` synthetic
    alias emails distinct from every other entry's addresses. `role` is fixed
    to a valid slug (`dev`) throughout -- role-mapping correctness is
    `test_role_map.py`'s subject, not this file's."""
    team = []
    for i in range(n):
        aliases = [f"{email_prefix}{i}-alias{a}@example.com" for a in range(aliases_per_entry)]
        team.append(
            {
                "email": f"{email_prefix}{i}@example.com",
                "name": f"Member {i}",
                "role": "dev",
                "aliases": aliases,
            }
        )
    return team


def _manifest_payload(program_id: str, team: list[dict[str, Any]]) -> dict[str, Any]:
    """Minimal valid manifest body -- the `program:` block is fixed/valid
    across every push in this file; only `team[]` size varies per scenario."""
    return {
        "programId": program_id,
        "program": {
            "name": "Payload Cap Test Program",
            "type": "Greenfield",
            "description": "Synthetic manifest for T-13 payload-cap tests.",
        },
        "team": team,
    }


# -----------------------------------------------------------------------------
# Row-count helpers -- mirror test_manifest_auth_scope.py's (T-11) "nothing
# written" pattern and test_manifest_roster_removal.py's (T-12)
# populate_existing=True re-fetch guard (AF-14).
# -----------------------------------------------------------------------------


async def _write_counts(session: AsyncSession) -> tuple[int, int, int]:
    """`(program_roster, program_summary, user_roles)` row counts, unfiltered
    by program_id -- every table AC-8 implies "nothing is written" means on a
    413. Mirrors test_manifest_auth_scope.py::_write_counts."""
    roster = (
        await session.execute(sa.select(sa.func.count()).select_from(ProgramRoster))
    ).scalar_one()
    summary = (
        await session.execute(sa.select(sa.func.count()).select_from(ProgramSummary))
    ).scalar_one()
    roles = (await session.execute(sa.select(sa.func.count()).select_from(UserRole))).scalar_one()
    return roster, summary, roles


async def _roster_row_count(session: AsyncSession, program_id: str) -> int:
    """Total `program_roster` row count for one `program_id` -- AF-14:
    `execution_options(populate_existing=True)` guards against the ORM
    identity map handing back a stale cached row after a raw Core upsert."""
    result = await session.execute(
        repopulate(
            sa.select(sa.func.count())
            .select_from(ProgramRoster)
            .where(ProgramRoster.program_id == program_id)
        )
    )
    return result.scalar_one()


# -----------------------------------------------------------------------------
# HTTP-level helpers -- mirror test_manifest_auth_scope.py (T-11): real
# create_app() instance, get_db overridden to the disposable test_session,
# a locally-seeded ingest token (per-file-scaffold-ownership precedent).
# -----------------------------------------------------------------------------


async def _seed_token(
    test_session: AsyncSession, *, label: str, allowed_program_ids: list[str]
) -> str:
    """Seed one `ingest_tokens` row directly, returning the raw bearer token.
    Mirrors test_manifest_auth_scope.py::_seed_token / test_ingest_token_auth.py."""
    raw_token = "hrn_pat_" + secrets.token_hex(32)
    row = IngestToken(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        label=label,
        user_email="owner@example.com",
        allowed_program_ids=allowed_program_ids,
        expires_at=None,
        revoked_at=None,
    )
    test_session.add(row)
    await test_session.commit()
    return raw_token


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_manifest_app(build_app: Callable[..., FastAPI], test_session: AsyncSession) -> FastAPI:
    """Real `create_app()` instance, `get_db` overridden to the disposable
    `test_session` -- mirrors test_manifest_auth_scope.py::_build_manifest_app."""
    app = build_app()
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


async def _post_manifest(
    async_client_for: AsyncClientFactory,
    app: FastAPI,
    *,
    payload: dict[str, Any],
    token: str,
) -> Response:
    async with async_client_for(app) as client:
        return await client.post(
            _MANIFEST_PATH, json=payload, headers={"Authorization": f"Bearer {token}"}
        )


# -----------------------------------------------------------------------------
# HTTP path (router's own _TEAM_ENTRY_CAP, app/api/manifest.py) -- the real
# client-facing enforcement point.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_over_cap_returns_413_and_writes_nothing_http_ac8(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """501 raw team[] entries, submitted through the real HTTP route with a
    validly-scoped token -- the router's own cap check must reject this
    before ingest_manifest() is ever called, so nothing is written to any of
    the three tables AC-1/AC-2's "nothing is written" pattern already covers."""
    program_id = "prog-payload-cap-http-over"
    token = await _seed_token(
        test_session, label="t13-http-over", allowed_program_ids=[program_id]
    )
    app = _build_manifest_app(build_app, test_session)

    payload = _manifest_payload(program_id, _build_team(_CAP + 1))
    resp = await _post_manifest(async_client_for, app, payload=payload, token=token)

    assert resp.status_code == 413
    assert resp.json()["error"]["message"] == "team exceeds the 500-entry cap"
    assert await _write_counts(test_session) == (0, 0, 0)


@pytest.mark.asyncio
async def test_over_cap_http_emits_ingest_manifest_write_af09(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """AF-09 regression guard: the HTTP 413 path MUST emit
    `ingest_manifest_write`.

    Before AF-09 was resolved (2026-09-08) the router short-circuited on the
    cap before `ingest_manifest()` ran, so the service's own 413 logging branch
    was unreachable over HTTP and an operator watching logs saw *nothing* for a
    rejected oversized push -- while FR-2 documented that the event fires on
    every outcome. The router now emits it itself, via the shared
    `log_ingest_manifest_write`.

    Asserted here rather than in `test_manifest_pii_logging.py` because this
    file already owns the HTTP + token-minting setup; that file calls the
    service directly and would need the whole HTTP harness duplicated.

    Also re-asserts the FR-2 field allowlist and the absence of PII on this
    newly-reachable path -- a new emission site is exactly where an
    `email`/`name` leak would slip in unnoticed."""
    program_id = "prog-payload-cap-http-log"
    token = await _seed_token(
        test_session, label="t13-http-log", allowed_program_ids=[program_id]
    )
    app = _build_manifest_app(build_app, test_session)

    # Distinctive synthetic PII, so an interpolation leak is unmistakable.
    team = _build_team(_CAP + 1)
    team[0]["email"] = "zzyzx.af09probe@example.invalid"
    team[0]["name"] = "Zzyzx Af09Probe Synthetic"
    payload = _manifest_payload(program_id, team)

    # `caplog` cannot see this event: `configure_logging()`'s dictConfig
    # disables pre-existing loggers, so the record never reaches the root
    # handler caplog installs. Same trap `test_manifest_pii_logging.py`
    # documents -- capture off the real logger directly, force-enabling it and
    # restoring the original state afterwards.
    logger = logging.getLogger("app.services.manifest_ingest")
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _Capture()
    original = (logger.disabled, logger.propagate, logger.level)
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        resp = await _post_manifest(async_client_for, app, payload=payload, token=token)
    finally:
        logger.removeHandler(handler)
        logger.disabled, logger.propagate, logger.level = original

    assert resp.status_code == 413
    assert await _write_counts(test_session) == (0, 0, 0)

    events = [r for r in captured if r.getMessage() == "ingest_manifest_write"]
    assert len(events) == 1, (
        "expected exactly one ingest_manifest_write on the HTTP 413 path "
        f"(AF-09); saw {len(events)}"
    )
    record = events[0]

    # FR-2 required field set, and the values the router mirrors from the
    # service's own 413 branch so the two layers look identical in the stream.
    #
    # Read through `record.__dict__` rather than attribute access: these are
    # injected via `logger.info(..., extra={...})`, so mypy cannot see them on
    # `LogRecord` and `record.program_id` fails type-checking with
    # `[attr-defined]`. test_manifest_pii_logging.py sidesteps the same problem
    # by formatting through JSONFormatter into a dict.
    fields: dict[str, Any] = record.__dict__
    assert fields["program_id"] == program_id
    assert fields["token_label"] == "t13-http-log"
    assert fields["identity_written"] is False
    assert fields["roster_received"] == _CAP + 1
    assert fields["roster_valid"] == 0
    assert fields["roster_created"] == 0
    assert fields["roster_updated"] == 0
    assert fields["roster_removed"] == 0
    assert fields["roster_rejected"] == 0
    assert isinstance(fields["duration_ms"], int)

    # No PII, in structured fields or interpolated into the rendered message.
    rendered = json.dumps(fields, default=str)
    assert "zzyzx.af09probe@example.invalid" not in rendered
    assert "Zzyzx Af09Probe Synthetic" not in rendered
    assert not hasattr(record, "email")
    # NB: deliberately NOT `hasattr(record, "name")` -- every LogRecord carries
    # a built-in `name` holding the LOGGER name ("app.services.manifest_ingest"),
    # so that assertion can never pass and would say nothing about PII. The
    # value-based checks above are what actually prove the person's name never
    # reaches the record, in a field or interpolated into the message.
    assert fields["name"] == "app.services.manifest_ingest"


@pytest.mark.asyncio
async def test_at_cap_boundary_accepted_http_ac8(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """Exactly 500 raw team[] entries -- the cap is "greater than 500", so
    the boundary value itself must be accepted, not rejected."""
    program_id = "prog-payload-cap-http-at"
    token = await _seed_token(test_session, label="t13-http-at", allowed_program_ids=[program_id])
    app = _build_manifest_app(build_app, test_session)

    payload = _manifest_payload(program_id, _build_team(_CAP))
    resp = await _post_manifest(async_client_for, app, payload=payload, token=token)

    assert resp.status_code == 200
    body = resp.json()
    assert body["roster"]["received"] == _CAP
    assert body["roster"]["valid"] == _CAP
    assert await _roster_row_count(test_session, program_id) == _CAP


# -----------------------------------------------------------------------------
# Service path (manifest_ingest.py's own _TEAM_ENTRY_CAP) -- defence-in-depth
# for a direct caller that bypasses the router entirely.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_over_cap_raises_413_and_writes_nothing_ac8(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """501 raw team[] entries, calling ingest_manifest() directly -- its own
    internal cap check must raise HTTPException(413) before any Tier-1
    (program: block) or Tier-2 (team[] entry) validation runs, so identity is
    never written either, not just the roster."""
    program_id = "prog-payload-cap-svc-over"
    payload = _manifest_payload(program_id, _build_team(_CAP + 1))

    with pytest.raises(HTTPException) as exc_info:
        await ingest_manifest(
            db=test_session, program_id=program_id, payload=payload, token_label=_TOKEN_LABEL
        )

    assert exc_info.value.status_code == 413
    assert await _write_counts(test_session) == (0, 0, 0)


@pytest.mark.asyncio
async def test_service_at_cap_boundary_accepted_ac8(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """Exactly 500 raw team[] entries, calling ingest_manifest() directly --
    accepted, one program_roster row per entry (no aliases here)."""
    program_id = "prog-payload-cap-svc-at"
    payload = _manifest_payload(program_id, _build_team(_CAP))

    response = await ingest_manifest(
        db=test_session, program_id=program_id, payload=payload, token_label=_TOKEN_LABEL
    )

    assert response.roster.received == _CAP
    assert response.roster.valid == _CAP
    assert await _roster_row_count(test_session, program_id) == _CAP


@pytest.mark.asyncio
async def test_service_under_cap_with_many_aliases_accepted_pre_expansion_fr5(
    migrated_db: AlembicRunner, test_session: AsyncSession
) -> None:
    """400 raw team[] entries, each with 2 aliases -- 1200 resulting
    program_roster rows, but the cap counts DECLARED entries, not expanded
    rows, so this is well under the 500-entry cap and must be accepted. A
    test that only checked "many rows -> 413" would encode the wrong rule
    and still pass today (FR-5's pre-alias-expansion semantics, see module
    docstring)."""
    program_id = "prog-payload-cap-svc-aliases"
    entry_count = 400
    payload = _manifest_payload(
        program_id, _build_team(entry_count, aliases_per_entry=2)
    )

    response = await ingest_manifest(
        db=test_session, program_id=program_id, payload=payload, token_label=_TOKEN_LABEL
    )

    # Received/valid are entry-granularity (D-07), never expanded-row count.
    assert response.roster.received == entry_count
    assert response.roster.valid == entry_count
    assert await _roster_row_count(test_session, program_id) == entry_count * 3
