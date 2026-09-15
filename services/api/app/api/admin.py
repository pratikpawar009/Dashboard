"""Router for `POST /api/admin/scan-repos` (admin-scan-api, ING-07 D-05).

Wire contract: ING-07 PLAN.md §3 F-01 -- one route, wildcard-strict
`ingest-token-auth`, delegates to `app/services/repo_scan.py::scan_org_repos`.

D-05 (this feature's decision log) -- follows `app/api/manifest.py`'s
pattern verbatim: the router creates its own `HTTPBearer(auto_error=False)`
instance, resolves `credentials` + `session` locally, and calls
`app/core/ingest_auth.py::get_ingest_token()` as a plain coroutine passing
the literal sentinel `program_id="*"`. Reasoning matches `manifest.py`'s
module docstring -- `get_ingest_token`'s own `program_id: str` parameter
carries no `Path`/`Query` annotation, so `Depends()` would bind it as a
required query parameter this contract does not accept. This is full reuse
of the dependency's 401 (missing / unknown / revoked / expired) and 403
(scope) logic -- only the calling convention differs; no denial branch is
duplicated here. Never imports `ingest_auth._http_bearer` (private there
per that module's FR-6 structural isolation).

Wildcard-strict re-check (FR-2 / TC-13): the shared dependency's scope
check accepts both the `"*"` wildcard AND the allow-all-empty legacy
default (ADR-0006 § Consequences). This admin endpoint requires the
strictest form -- literal `"*"` in `allowed_program_ids`. The router
therefore re-checks membership itself and raises 403 with a distinct
detail (`"wildcard scope required"`) so a caller / test can distinguish
this router-level rejection from `get_ingest_token`'s own 403 (`"scope"`).

Ordering (FR-5 / TC-04..TC-08): auth first (401/403 from
`get_ingest_token`), then router-level wildcard re-check (403), then
missing-config 500. Config check runs in the HANDLER BODY, not a
dependency, so 401/403 fire even when config is missing. A dep raising
500 before auth would break TC-04's "no header -> 401" expectation.

PII (`.claude/rules/security-baseline.md`, NFR-security / TC-17): this
router NEVER logs the `Authorization` header value, the resolved bearer,
the `github_token` PAT, or any raw GitHub response body. `admin_scan_started`
carries only `{"org": <github_org>}`; `admin_scan_failed` carries
`{"org", "error_kind", "duration_ms"}` where `error_kind` is the
categorical label from `GitHubScanError` -- never `str(exc)`.
`admin_scan_completed` is emitted by the service layer (single emitter --
TC-18 asserts exactly one record).

Transaction boundary: `scan_org_repos()` performs the rollup upsert on
the request-scoped session but does NOT commit -- this router commits on
the success path only. On `GitHubScanError` the exception propagates,
`get_db()`'s `async with SessionLocal()` closes the session without a
commit, and the rollup is left untouched (FR-4 no-partial-write, TC-09,
TC-10, TC-11).
"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.ingest_auth import get_ingest_token
from app.schemas.repo_scan import ScanReposResponse
from app.services.repo_scan import GitHubScanError, scan_org_repos

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Fresh instance -- see module docstring (D-05). Never import
# `ingest_auth._http_bearer`.
_http_bearer = HTTPBearer(auto_error=False)

# D-05 -- sentinel handed to `get_ingest_token` so both `["*"]` and `[]`
# (allow-all-empty) tokens pass its shared scope check; the router's own
# re-check below rejects `[]`.
_WILDCARD_SENTINEL = "*"


@router.post(
    "/scan-repos",
    status_code=status.HTTP_200_OK,
    response_model=ScanReposResponse,
    responses={
        401: {"description": "Missing / unknown / revoked / expired bearer"},
        403: {"description": "Bearer lacks explicit wildcard scope"},
        500: {"description": "Server misconfigured (GITHUB_ORG or GITHUB_TOKEN unset)"},
        502: {"description": "GitHub upstream failed after retry budget"},
    },
)
async def scan_repos(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScanReposResponse:
    """`POST /api/admin/scan-repos` (admin-scan-api, ING-07-AC-1..AC-6).

    See the module docstring for why `get_ingest_token()` is called directly
    (D-05), why the wildcard re-check + missing-config check live in the
    handler body (ordering: TC-04..TC-08), and what fields the boundary
    log events carry (PII discipline / TC-17).
    """
    # Auth + shared scope check (401 missing/unknown/revoked/expired, 403 scope)
    # -- full reuse of get_ingest_token per D-05. `program_id="*"` is the
    # sentinel; the router re-checks strict wildcard membership below.
    ingest_token = await get_ingest_token(
        program_id=_WILDCARD_SENTINEL, credentials=credentials, session=session
    )

    # FR-2 / TC-13 -- router-level wildcard-strict re-check. `get_ingest_token`
    # accepted an allow-all-empty (`[]`) legacy token because ADR-0006 treats
    # that as unscoped; this admin endpoint requires the literal `"*"`.
    # Distinct detail so TC-13 can tell this 403 apart from get_ingest_token's.
    if _WILDCARD_SENTINEL not in ingest_token.allowed_program_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="wildcard scope required",
        )

    # FR-5 / TC-07, TC-08 -- ordered missing-config 500. Runs AFTER auth so a
    # missing bearer still gets 401 (TC-04). Empty string counts as missing
    # per FR-5 (FLAGS AF-01). Fires BEFORE any GitHub call and BEFORE any DB
    # write, so `org_summary_rollup` and `admin_scan_completed` are untouched.
    if not settings.github_org:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="missing configuration: GITHUB_ORG",
        )
    if not settings.github_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="missing configuration: GITHUB_TOKEN",
        )

    # Boundary log -- `org` only. NEVER `credentials.credentials` or
    # `settings.github_token` (TC-17).
    logger.info("admin_scan_started", extra={"org": settings.github_org})

    started = time.perf_counter()
    try:
        response = await scan_org_repos(
            session,
            github_org=settings.github_org,
            github_token=settings.github_token,
        )
    except GitHubScanError as exc:
        # FR-3 / FR-4 -- retry-exhaustion / hung upstream -> 502; the
        # request-scoped session is closed without commit by get_db()'s
        # async-with, so the rollup upsert queued inside scan_org_repos
        # never lands (TC-09, TC-10, TC-11). `error_kind` is the categorical
        # label from GitHubScanError -- str(exc) is never logged (TC-17).
        logger.info(
            "admin_scan_failed",
            extra={
                "org": settings.github_org,
                "error_kind": exc.error_kind,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="github upstream failed",
        ) from None

    # `scan_org_repos` performs the upsert but does not commit -- the router
    # owns the transaction boundary (D-02, FR-4). `admin_scan_completed` is
    # emitted by the service (single emitter -- TC-18 asserts exactly one).
    await session.commit()
    return response
