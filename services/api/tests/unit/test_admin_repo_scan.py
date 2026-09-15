"""ING-07 T-07 -- integration / contract / security tests for
`POST /api/admin/scan-repos` (`app/api/admin.py` + `app/services/repo_scan.py`).

One test per non-perf test case in `docs/test-cases/ING-07.json`
(TC-01..TC-15, TC-17..TC-20). TC-16 (perf) is owned by T-08. Every test
function docstring quotes its JSON `then` / `expected_results` verbatim so
the file traces to the test-case doc row-for-row.

Scaffold: `build_app`/`async_client_for`/`migrated_db`/`test_session` from
`tests/conftest.py`, plus the ING-07 fixture family that T-06 authored in
that same file (respx route factories, ingest-token seeds, rollup seeds,
settings-override dicts, `no_sleep`, `structlog_capture`, `openapi_schema`,
`background_rebuild_task`). `get_db` is overridden per app to yield the
caller's own `test_session`, so seeding, the HTTP call, and post-call
rollup re-fetches all share one live connection to the disposable test DB.

Log-capture note (T-06 conftest header): `structlog_capture` hooks
`app.services.repo_scan` -- not `app.api.admin`. Where a test needs the
router's own `admin_scan_started` / `admin_scan_failed` records too
(TC-17), the test enables the `app.api.admin` logger inline via
`_enable_logger`; the shipped code uses stdlib `logging` throughout
(no structlog anywhere under `services/api/**`).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
import respx
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.rollup import OrgSummaryRollup
from app.services.rollup_rebuild import RebuildResult
from tests.conftest import AlembicRunner, SeededIngestToken, repopulate

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]
OpenAPISchemaFetcher = Callable[[AsyncClient], Awaitable[dict[str, Any]]]

_PATH = "/api/admin/scan-repos"
_ORG_ID = "org-1"
_SENTINEL_PAT = "ghp_SENTINEL_DO_NOT_LOG_ABC123"  # noqa: S105 - TC-17 sentinel
_SENTINEL_BODY = f"upstream error mentioning {_SENTINEL_PAT}"


# -----------------------------------------------------------------------------
# App + DB-override scaffold. Same shape as test_personal_usage.py /
# test_manifest_ingest.py: one session shared across seed, request, and
# post-request re-fetch, so identity-map staleness is only a concern for the
# rollup re-read (handled via `repopulate`).
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_admin_app(
    build_app: Callable[..., FastAPI],
    session: AsyncSession,
    **settings_overrides: Any,
) -> FastAPI:
    app = build_app(**settings_overrides)
    app.dependency_overrides[get_db] = _db_override(session)
    return app


async def _refetch_rollup(session: AsyncSession) -> OrgSummaryRollup:
    """Re-read the singleton rollup row bypassing the identity map (AF-14)."""
    result = await session.execute(
        repopulate(sa.select(OrgSummaryRollup).where(OrgSummaryRollup.org_id == _ORG_ID))
    )
    return result.scalar_one()


def _auth(bearer: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {bearer}"}


def _rollup_snapshot(row: OrgSummaryRollup) -> tuple[int, int, datetime]:
    """Byte-comparable tuple of the three mutable columns FR-4 owns."""
    return row.repos_total, row.repos_with_harness_installed, row.as_of_timestamp


# -----------------------------------------------------------------------------
# Log-capture helper -- structlog_capture only hooks
# `app.services.repo_scan`; TC-17 also needs to see (or verify the absence of
# a leak on) the router's own records. Mirrors the disabled-logger
# reset the T-06 fixture already documents.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _enable_logger(name: str) -> Iterator[list[logging.LogRecord]]:
    logger = logging.getLogger(name)
    original_disabled = logger.disabled
    original_level = logger.level
    logger.disabled = False
    logger.setLevel(logging.DEBUG)
    handler = _RecordCapturingHandler()
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.disabled = original_disabled
        logger.setLevel(original_level)


def _record_contains(record: logging.LogRecord, needle: str) -> bool:
    """True iff `needle` appears anywhere in the record's message or extras."""
    if needle in str(record.msg):
        return True
    for key, value in record.__dict__.items():
        if key in {"msg", "args"}:
            continue
        if needle in str(value):
            return True
    return False


def _parse_iso_z(value: str) -> datetime:
    """Parse an ISO-8601 timestamp whose UTC offset is `Z` (TC-12 shape)."""
    assert value.endswith("Z"), f"expected `Z` suffix, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# =============================================================================
# TC-01 -- happy path: mixed org classifies each repo and upserts rollup.
# =============================================================================


@pytest.mark.asyncio
async def test_tc01_happy_path_mixed_org_classifies_and_upserts_rollup(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_200_mixed: Callable[..., respx.Route],
    github_contents_program_yaml_200: Callable[..., respx.Route],
    github_contents_program_yaml_404: Callable[..., respx.Route],
) -> None:
    """endpoint returns 200 and `org_summary_rollup` for `org-1` is upserted to
    `repos_total=3`, `repos_with_harness_installed=2`, `as_of_timestamp=now`."""
    github_list_repos_200_mixed(names=("repo-a", "repo-b", "repo-c"))
    github_contents_program_yaml_200("repo-a")
    github_contents_program_yaml_200("repo-b")
    github_contents_program_yaml_404("repo-c")

    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["repos_total"] == 3
    assert body["repos_with_harness_installed"] == 2
    body_ts = _parse_iso_z(body["as_of_timestamp"])

    row = await _refetch_rollup(test_session)
    assert row.repos_total == 3
    assert row.repos_with_harness_installed == 2
    assert row.as_of_timestamp == body_ts


# =============================================================================
# TC-02 -- AC1 boundary: every repo installed.
# =============================================================================


@pytest.mark.asyncio
async def test_tc02_all_repos_installed_full_count(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_200_all_installed: Callable[..., respx.Route],
    github_contents_program_yaml_200: Callable[..., respx.Route],
) -> None:
    """rollup is upserted with `repos_total=3` and `repos_with_harness_installed=3`."""
    github_list_repos_200_all_installed(names=("repo-a", "repo-b", "repo-c"))
    for repo in ("repo-a", "repo-b", "repo-c"):
        github_contents_program_yaml_200(repo)

    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["repos_total"] == 3
    assert body["repos_with_harness_installed"] == 3
    row = await _refetch_rollup(test_session)
    assert row.repos_total == 3
    assert row.repos_with_harness_installed == 3


# =============================================================================
# TC-03 -- AC1 boundary: no repos installed.
# =============================================================================


@pytest.mark.asyncio
async def test_tc03_no_repos_installed_zero_count(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_200_none_installed: Callable[..., respx.Route],
    github_contents_program_yaml_404: Callable[..., respx.Route],
) -> None:
    """rollup is upserted with `repos_total=3` and `repos_with_harness_installed=0`."""
    github_list_repos_200_none_installed(names=("repo-a", "repo-b", "repo-c"))
    for repo in ("repo-a", "repo-b", "repo-c"):
        github_contents_program_yaml_404(repo)

    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["repos_total"] == 3
    assert body["repos_with_harness_installed"] == 0
    row = await _refetch_rollup(test_session)
    assert row.repos_total == 3
    assert row.repos_with_harness_installed == 0


# =============================================================================
# TC-04 -- AC2: missing Authorization header -> 401, no GitHub call, rollup
# untouched.
# =============================================================================


@pytest.mark.asyncio
async def test_tc04_missing_authorization_header_returns_401_no_side_effects(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
) -> None:
    """endpoint returns 401, no request is issued to `api.github.com`, and
    `org_summary_rollup` is unchanged."""
    before = _rollup_snapshot(org_summary_rollup_seed)
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH)  # no header at all

    assert resp.status_code == 401, resp.text
    assert len(respx_mock.calls) == 0
    row = await _refetch_rollup(test_session)
    assert _rollup_snapshot(row) == before


# =============================================================================
# TC-05 -- AC2: revoked / unknown token -> 401, no GitHub call, rollup
# untouched.
# =============================================================================


@pytest.mark.asyncio
async def test_tc05_unknown_bearer_returns_401_no_side_effects(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
) -> None:
    """endpoint returns 401, no GitHub call is made, and the rollup row is
    unchanged."""
    before = _rollup_snapshot(org_summary_rollup_seed)
    unknown_bearer = "hrn_pat_" + secrets.token_hex(32)  # never seeded
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(unknown_bearer))

    assert resp.status_code == 401, resp.text
    assert len(respx_mock.calls) == 0
    row = await _refetch_rollup(test_session)
    assert _rollup_snapshot(row) == before


# =============================================================================
# TC-06 -- AC3: valid token without '*' -> 403, no GitHub call.
# =============================================================================


@pytest.mark.asyncio
async def test_tc06_program_scoped_bearer_returns_403(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_program_scoped: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
) -> None:
    """endpoint returns 403, no GitHub call is made, and the rollup row is
    unchanged."""
    before = _rollup_snapshot(org_summary_rollup_seed)
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_program_scoped.bearer))

    assert resp.status_code == 403, resp.text
    assert len(respx_mock.calls) == 0
    row = await _refetch_rollup(test_session)
    assert _rollup_snapshot(row) == before


# =============================================================================
# TC-07 -- AC4: missing GITHUB_TOKEN -> 500, no GitHub call, no completed log.
# =============================================================================


@pytest.mark.asyncio
async def test_tc07_missing_github_token_returns_500_no_side_effects(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_missing_github_token: dict[str, Any],
    structlog_capture: list[logging.LogRecord],
) -> None:
    """endpoint returns 500 with body {"detail": "missing configuration:
    GITHUB_TOKEN"}, no GitHub call is made, and `org_summary_rollup` +
    `admin_scan_completed` are untouched."""
    before = _rollup_snapshot(org_summary_rollup_seed)
    app = _build_admin_app(build_app, test_session, **settings_missing_github_token)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))

    assert resp.status_code == 500, resp.text
    # TC-07 JSON asserts `{"detail": ...}` verbatim, but this app wraps every
    # HTTPException via `app.core.errors.register_exception_handlers` per
    # ADR-0002 -> `{"error": {"code": "http_500", "message": <detail>, ...}}`.
    # The observable message must still match the FR-5 wording.
    body = resp.json()
    assert body["error"]["code"] == "http_500"
    assert body["error"]["message"] == "missing configuration: GITHUB_TOKEN"
    assert len(respx_mock.calls) == 0
    row = await _refetch_rollup(test_session)
    assert _rollup_snapshot(row) == before
    assert not any(r.msg == "admin_scan_completed" for r in structlog_capture)


# =============================================================================
# TC-08 -- AC4: missing GITHUB_ORG -> 500, no GitHub call, no completed log.
# =============================================================================


@pytest.mark.asyncio
async def test_tc08_missing_github_org_returns_500_no_side_effects(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_missing_github_org: dict[str, Any],
    structlog_capture: list[logging.LogRecord],
) -> None:
    """endpoint returns 500 with body {"detail": "missing configuration:
    GITHUB_ORG"}, no GitHub call is made, and `org_summary_rollup` +
    `admin_scan_completed` are untouched."""
    before = _rollup_snapshot(org_summary_rollup_seed)
    app = _build_admin_app(build_app, test_session, **settings_missing_github_org)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))

    assert resp.status_code == 500, resp.text
    # See TC-07 for the ADR-0002 wrapper note.
    body = resp.json()
    assert body["error"]["code"] == "http_500"
    assert body["error"]["message"] == "missing configuration: GITHUB_ORG"
    assert len(respx_mock.calls) == 0
    row = await _refetch_rollup(test_session)
    assert _rollup_snapshot(row) == before
    assert not any(r.msg == "admin_scan_completed" for r in structlog_capture)


# =============================================================================
# TC-09 -- AC5: list-repos 5xx after retries -> 502, rollup unchanged, exactly
# 4 attempts (1 initial + 3 retries per FR-3).
# =============================================================================


@pytest.mark.asyncio
async def test_tc09_list_repos_5xx_after_retries_returns_502(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_500: Callable[[], respx.Route],
    no_sleep: None,
) -> None:
    """endpoint returns 502 and `org_summary_rollup` keeps its prior values
    (exactly 4 attempts: 1 initial + 3 retries)."""
    before = _rollup_snapshot(org_summary_rollup_seed)
    route = github_list_repos_500()
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))

    assert resp.status_code == 502, resp.text
    assert route.call_count == 4
    row = await _refetch_rollup(test_session)
    assert _rollup_snapshot(row) == before


# =============================================================================
# TC-10 -- AC5: GitHub call exceeds 10 s timeout -> 502, rollup unchanged,
# test wall-clock < 1 s.
# =============================================================================


@pytest.mark.asyncio
async def test_tc10_list_repos_timeout_returns_502_within_1s(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_timeout: Callable[[], respx.Route],
    no_sleep: None,
) -> None:
    """endpoint returns 502 and the rollup is unchanged; the endpoint call
    completes in test-wall-clock < 1 s (timeout is raised, not slept),
    with 4 attempts recorded."""
    before = _rollup_snapshot(org_summary_rollup_seed)
    route = github_list_repos_timeout()
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    loop = asyncio.get_running_loop()
    started = loop.time()
    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))
    wall_s = loop.time() - started

    assert resp.status_code == 502, resp.text
    assert wall_s < 1.0, f"wall-clock {wall_s:.3f}s exceeded 1s budget"
    assert route.call_count == 4
    row = await _refetch_rollup(test_session)
    assert _rollup_snapshot(row) == before


# =============================================================================
# TC-11 -- AC5: focused non-mutation on 502 with realistic prior values.
# =============================================================================


@pytest.mark.asyncio
async def test_tc11_502_preserves_each_prior_column_individually(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_prior_values: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_500: Callable[[], respx.Route],
    no_sleep: None,
) -> None:
    """HTTP 502; `repos_total == 42` (unchanged); `repos_with_harness_installed
    == 17` (unchanged); `as_of_timestamp == '2026-08-01T00:00:00Z'`
    (unchanged)."""
    github_list_repos_500()
    prior_ts = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))

    assert resp.status_code == 502, resp.text
    row = await _refetch_rollup(test_session)
    assert row.repos_total == 42
    assert row.repos_with_harness_installed == 17
    assert row.as_of_timestamp == prior_ts


# =============================================================================
# TC-12 -- FR-1 contract: response body shape + OpenAPI component + persisted
# timestamp match.
# =============================================================================


@pytest.mark.asyncio
async def test_tc12_response_and_openapi_pin_scan_repos_response_contract(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_200_mixed: Callable[..., respx.Route],
    github_contents_program_yaml_mixed: Callable[..., dict[str, respx.Route]],
    openapi_schema: OpenAPISchemaFetcher,
) -> None:
    """response body validates against `ScanReposResponse` -- exactly three
    keys, int types, and `as_of_timestamp` is ISO-8601 UTC (`Z` suffix)
    matching the persisted rollup; the OpenAPI schema exports the same
    component."""
    github_list_repos_200_mixed(names=("repo-a", "repo-b"))
    github_contents_program_yaml_mixed(installed=("repo-a",), not_installed=("repo-b",))
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        schema = await openapi_schema(client)

    assert set(body.keys()) == {"repos_total", "repos_with_harness_installed", "as_of_timestamp"}
    # `bool` is a subclass of `int` in Python; ensure real ints, not bools.
    assert type(body["repos_total"]) is int
    assert type(body["repos_with_harness_installed"]) is int
    assert body["as_of_timestamp"].endswith("Z")
    assert "+" not in body["as_of_timestamp"]
    body_ts = _parse_iso_z(body["as_of_timestamp"])

    row = await _refetch_rollup(test_session)
    assert row.as_of_timestamp == body_ts

    component = schema["components"]["schemas"]["ScanReposResponse"]
    assert set(component["properties"].keys()) == {
        "repos_total",
        "repos_with_harness_installed",
        "as_of_timestamp",
    }
    assert component["properties"]["repos_total"]["type"] == "integer"
    assert component["properties"]["repos_with_harness_installed"]["type"] == "integer"
    assert component["properties"]["as_of_timestamp"]["type"] == "string"


# =============================================================================
# TC-13 -- FR-2: allow-all-empty (`[]`) token rejected 403 by the router's
# wildcard-strict re-check.
# =============================================================================


@pytest.mark.asyncio
async def test_tc13_allow_all_empty_bearer_rejected_by_router_wildcard_recheck(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_allow_all_empty: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
) -> None:
    """the router's own re-check rejects with 403 because the resolved token
    does NOT carry a literal `*` in `allowed_program_ids`; the 403
    originates from the router (distinct detail `wildcard scope required`),
    not from `get_ingest_token()` (which returns `scope`)."""
    before = _rollup_snapshot(org_summary_rollup_seed)
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_allow_all_empty.bearer))

    assert resp.status_code == 403, resp.text
    # Router-level 403 is `wildcard scope required` (distinct from
    # `get_ingest_token`'s `scope`), per app/api/admin.py FR-2 comment.
    # Wrapped by the ADR-0002 handler; the raw detail lands in `error.message`.
    body = resp.json()
    assert body["error"]["code"] == "http_403"
    assert body["error"]["message"] == "wildcard scope required"
    assert len(respx_mock.calls) == 0
    row = await _refetch_rollup(test_session)
    assert _rollup_snapshot(row) == before


# =============================================================================
# TC-14 -- FR-3: 429 retried once with backoff+jitter, scan succeeds.
# =============================================================================


@pytest.mark.asyncio
async def test_tc14_429_then_200_retries_once_and_succeeds(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_429_then_200: Callable[..., respx.Route],
    github_contents_program_yaml_200: Callable[..., respx.Route],
    no_sleep: None,
) -> None:
    """the wrapper retries once, the scan completes 200, and the rollup is
    upserted normally; exactly 2 calls (1 initial + 1 retry) to list-repos."""
    list_route = github_list_repos_429_then_200(names=("repo-a",))
    github_contents_program_yaml_200("repo-a")
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["repos_total"] == 1
    assert body["repos_with_harness_installed"] == 1
    assert list_route.call_count == 2
    row = await _refetch_rollup(test_session)
    assert row.repos_total == 1
    assert row.repos_with_harness_installed == 1


# =============================================================================
# TC-15 -- FR-4: mid-scan probe failure -> 502, rollup untouched (no partial
# write), no completed log.
# =============================================================================


@pytest.mark.asyncio
async def test_tc15_mid_scan_probe_failure_returns_502_no_partial_write(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_prior_values: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_200_mixed: Callable[..., respx.Route],
    github_contents_program_yaml_200: Callable[..., respx.Route],
    github_contents_program_yaml_500: Callable[..., respx.Route],
    github_contents_program_yaml_404: Callable[..., respx.Route],
    structlog_capture: list[logging.LogRecord],
    no_sleep: None,
) -> None:
    """endpoint returns 502 and `org_summary_rollup` equals the prior real
    values (42 / 17 / 2026-08-01T00Z) bytes-identical; no
    `admin_scan_completed` structlog record emitted."""
    github_list_repos_200_mixed(names=("repo-a", "repo-b", "repo-c"))
    github_contents_program_yaml_200("repo-a")
    github_contents_program_yaml_500("repo-b")
    github_contents_program_yaml_404("repo-c")  # MAY not be called (iteration order)
    prior_ts = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))

    assert resp.status_code == 502, resp.text
    row = await _refetch_rollup(test_session)
    assert row.repos_total == 42
    assert row.repos_with_harness_installed == 17
    assert row.as_of_timestamp == prior_ts
    assert not any(r.msg == "admin_scan_completed" for r in structlog_capture)


# =============================================================================
# TC-17 -- NFR-security: PAT and raw GitHub payloads never appear in logs or
# exception messages.
# =============================================================================


@pytest.mark.asyncio
async def test_tc17_pat_and_upstream_body_never_leak_into_logs_or_response(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured_sentinel_pat: dict[str, Any],
    github_list_repos_500_secret_bearing_body: Callable[[], respx.Route],
    structlog_capture: list[logging.LogRecord],
    caplog: pytest.LogCaptureFixture,
    no_sleep: None,
) -> None:
    """HTTP 502; no captured log record (structlog OR caplog) contains the
    sentinel PAT, the Authorization bearer, or the raw upstream body; and
    the 502 response body does not contain the sentinel or the
    Authorization header."""
    github_list_repos_500_secret_bearing_body()
    bearer = ingest_token_wildcard.bearer
    caplog.set_level(logging.DEBUG)
    app = _build_admin_app(build_app, test_session, **settings_github_configured_sentinel_pat)

    # `app.api.admin` may have been disabled by migrations/env.py's
    # `fileConfig(disable_existing_loggers=True)`; enable it inline so this
    # test genuinely exercises its records too (rather than passing vacuously
    # because everything from the router is silently dropped).
    with _enable_logger("app.api.admin") as admin_records:
        async with async_client_for(app) as client:
            resp = await client.post(_PATH, headers=_auth(bearer))

    assert resp.status_code == 502, resp.text
    body_text = resp.text
    for needle in (_SENTINEL_PAT, bearer):
        assert needle not in body_text, f"sentinel/bearer leaked into 502 body: {body_text!r}"

    all_records: list[logging.LogRecord] = [
        *structlog_capture,
        *admin_records,
        *caplog.records,
    ]
    for needle in (_SENTINEL_PAT, bearer, "Bearer ", _SENTINEL_BODY):
        for record in all_records:
            assert not _record_contains(record, needle), (
                f"log record leaked {needle!r}: {record.__dict__!r}"
            )


# =============================================================================
# TC-18 -- NFR-observability: `admin_scan_completed` emitted once on success
# with exact field set.
# =============================================================================


@pytest.mark.asyncio
async def test_tc18_admin_scan_completed_emitted_once_with_required_fields(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_200_mixed: Callable[..., respx.Route],
    github_contents_program_yaml_mixed: Callable[..., dict[str, respx.Route]],
    structlog_capture: list[logging.LogRecord],
) -> None:
    """exactly one structlog record is emitted with
    `event='admin_scan_completed'` carrying fields
    `{repos_total, repos_with_harness_installed, duration_ms, github_api_calls}`;
    `repos_total == 2`, `repos_with_harness_installed == 1`, `duration_ms`
    is `int >= 0`, and `github_api_calls` is `int >= 3` (1 list + 2 probes)."""
    github_list_repos_200_mixed(names=("repo-a", "repo-b"))
    github_contents_program_yaml_mixed(installed=("repo-a",), not_installed=("repo-b",))
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))

    assert resp.status_code == 200, resp.text
    completed = [r for r in structlog_capture if r.msg == "admin_scan_completed"]
    assert len(completed) == 1, [r.msg for r in structlog_capture]
    rec = completed[0]
    # `extra={}` fields become instance attributes at runtime; mypy can't see them.
    for field in ("repos_total", "repos_with_harness_installed", "duration_ms", "github_api_calls"):
        assert hasattr(rec, field), f"missing field {field!r} on {rec.__dict__!r}"
    assert getattr(rec, "repos_total") == 2
    assert getattr(rec, "repos_with_harness_installed") == 1
    duration_ms = getattr(rec, "duration_ms")
    assert isinstance(duration_ms, int) and duration_ms >= 0
    github_api_calls = getattr(rec, "github_api_calls")
    assert isinstance(github_api_calls, int) and github_api_calls >= 3


# =============================================================================
# TC-19 -- Idempotency: two consecutive successful scans over unchanged state
# produce identical repo counts.
# =============================================================================


@pytest.mark.asyncio
async def test_tc19_two_consecutive_scans_produce_identical_counts(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_seed: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_200_mixed: Callable[..., respx.Route],
    github_contents_program_yaml_mixed: Callable[..., dict[str, respx.Route]],
) -> None:
    """both responses report the same `repos_total` and
    `repos_with_harness_installed`, and the persisted row equals the last
    scan's result; `as_of_timestamp` advances (B >= A) and is NOT part of
    the equality assertion."""
    github_list_repos_200_mixed(names=("repo-a", "repo-b", "repo-c"))
    github_contents_program_yaml_mixed(
        installed=("repo-a", "repo-b"), not_installed=("repo-c",)
    )
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    async with async_client_for(app) as client:
        resp_a = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))
        resp_b = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))

    assert resp_a.status_code == 200, resp_a.text
    assert resp_b.status_code == 200, resp_b.text
    body_a, body_b = resp_a.json(), resp_b.json()
    assert body_a["repos_total"] == body_b["repos_total"] == 3
    assert body_a["repos_with_harness_installed"] == body_b["repos_with_harness_installed"] == 2

    row = await _refetch_rollup(test_session)
    assert row.repos_total == 3
    assert row.repos_with_harness_installed == 2

    ts_a = _parse_iso_z(body_a["as_of_timestamp"])
    ts_b = _parse_iso_z(body_b["as_of_timestamp"])
    assert row.as_of_timestamp == ts_b  # last-write-wins
    assert ts_b >= ts_a


# =============================================================================
# TC-20 -- Concurrent-rebuild tolerance: endpoint completes 200 while BED-03
# rebuild races on the same row.
# =============================================================================


@pytest.mark.asyncio
async def test_tc20_scan_completes_while_bed03_rebuild_races(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
    respx_mock: respx.MockRouter,
    ingest_token_wildcard: SeededIngestToken,
    org_summary_rollup_prior_values: OrgSummaryRollup,
    settings_github_configured: dict[str, Any],
    github_list_repos_200_mixed: Callable[..., respx.Route],
    github_contents_program_yaml_mixed: Callable[..., dict[str, respx.Route]],
    background_rebuild_task: Callable[[], asyncio.Task[RebuildResult]],
) -> None:
    """the endpoint returns 200 without deadlock or serialization error, per
    D-02's accepted last-write-wins race; the `org_summary_rollup` singleton
    row still exists (proving no rollback / no deadlock aborted either
    writer). Per D-02 verbatim: "no assertion is made on which writer wins"
    — and factually both writers are legitimate:
      - scan wins  → repos_total=2 (mixed fixture: 2 repos, 1 installed)
      - rebuild wins → repos_total=0 (`_build_org_summary` has no
        `usage_events` analog for repo counts and hard-codes 0 per D-03 of
        BED-03 — see rollup_rebuild.py:519). This corrects the earlier
        docstring claim that "rebuild did not touch repo counts": it does
        touch them, deliberately, and zeroes them.
    Ordering is timing-dependent (varies between isolated and full-suite
    runs); asserting on the value would encode that timing and contradict
    D-02."""
    github_list_repos_200_mixed(names=("repo-a", "repo-b"))
    github_contents_program_yaml_mixed(installed=("repo-a",), not_installed=("repo-b",))
    app = _build_admin_app(build_app, test_session, **settings_github_configured)

    rebuild_task = background_rebuild_task()
    try:
        async with async_client_for(app) as client:
            resp = await client.post(_PATH, headers=_auth(ingest_token_wildcard.bearer))
    finally:
        # Always await the task so any exception surfaces here rather than a
        # trailing "Task exception was never retrieved" warning.
        await rebuild_task

    assert resp.status_code == 200, resp.text
    # Per D-02: assert only that the row still exists (no deadlock rolled
    # either writer back). `_refetch_rollup` raises if the row is missing.
    await _refetch_rollup(test_session)
