"""Router for `POST /api/ingest/files` (ingest-files-api, ADR-0012, D-01).

Wire contract (frozen): `docs/requirements/api.md#ingest-files-api` --
`{program_id, kind: "activity", rows: [ActivityRowIn, ...]}` with the
5000-row envelope cap. Success is `200` with an `IngestFilesResponse`
body -- see PLAN.md § 2 F-01 (`output: 200 IngestFilesResponse | 400 |
401 | 403 | 404 | 413`).

D-02: this is the ING-02 router. The unregistered stub at
`app/api/ingest.py` stays untouched here; its deletion is T-06's scope,
not T-05's.

Auth wiring mirrors `app/api/manifest.py` verbatim (FR-5 / C-4): the
envelope's `program_id` lives in the JSON body, not path/query, and
`get_ingest_token`'s own `program_id: str` parameter has no `Path`/`Query`
annotation -- Depends() would bind it as a required query parameter this
contract does not accept. So the body is parsed first, `program_id` read
off the raw dict, and `get_ingest_token()` is called directly as a
coroutine (not via `Depends()`), passing that same `program_id` plus a
locally-resolved `credentials`/`session`. This is full reuse of the
dependency's 401 (missing/unknown/revoked/expired) and 403 (scope) logic,
only the calling convention differs; no denial branch is re-implemented
here. `_http_bearer` below is a fresh `HTTPBearer(auto_error=False)`
instance mirroring `ingest_auth.py`'s own construction -- that module's
own instance is private and never imported (FR-6 structural isolation).

D-01 / ADR-0012 -- `rebuild_org_rollups()` runs OUT-OF-BAND from the
request path via FastAPI `BackgroundTasks`. This router NEVER calls
`rebuild_org_rollups` directly; it hands
`activity_ingest.ingest_files()` an `on_org_rebuild` callable wired to
`background_tasks.add_task(dispatch_org_rebuild)`. The service invokes
that callable once, synchronously, AFTER commit + program-scope
rebuild -- `background_tasks.add_task` just schedules (no I/O), and
`dispatch_org_rebuild` opens its own `AsyncSession` from `SessionLocal`
because the request-scoped session is closed by the time the
BackgroundTask fires (DATA-DESIGN.md § 5). Exceptions inside that task
are logged via `logger.exception("ingest_org_rollup_task_failed")` in
`activity_ingest.py` with no PII.

Request-tier order (PLAN.md § 2 T-05, tasks.json T-05 notes): parse JSON
-> dict check -> `program_id` str check -> envelope `kind` via
`accept_envelope_kind` (400 on reject, FR-7 / AC-4 abort tier) ->
`await get_ingest_token(...)` (401/403) -> `len(rows) > 5000` (413,
AC-4). Envelope `kind` is validated BEFORE auth to match `api.md`'s
"400: envelope invalid ... Router-tier check, before auth" ordering; the
row cap is checked AFTER auth so an unauthenticated caller cannot use
payload size to probe scope. The service layer also enforces the row cap
as defence-in-depth (`activity_ingest._ENVELOPE_ROW_CAP`).

PII (`.claude/rules/security-baseline.md`, FR-8 / C-7): this router
never logs any request field. The single `ingest_write_completed` event
lives in `activity_ingest.py` with a keyword-only allowlist; auth
denials are logged inside `ingest_auth.py`. No `email`, `user`,
`command`, `feature`, `session_id`, or raw body is written to any
logger at any level here.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.ingest_auth import get_ingest_token
from app.core.ingest_kind import accept_envelope_kind
from app.schemas.ingest_files import IngestFilesResponse
from app.services.activity_ingest import dispatch_org_rebuild, ingest_files

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["ingest-files"])

# Fresh instance -- see module docstring (FR-6). Never import
# `ingest_auth._http_bearer`.
_http_bearer = HTTPBearer(auto_error=False)

# AC-4 -- envelope row cap enforced at the router tier before any DB work.
# `activity_ingest._ENVELOPE_ROW_CAP` mirrors this constant as
# defence-in-depth (module docstring, api.md#ingest-files-api § limits).
_ENVELOPE_ROW_CAP = 5_000


@router.post("/files", status_code=status.HTTP_200_OK, response_model=IngestFilesResponse)
async def push_files(
    request: Request,
    background_tasks: BackgroundTasks,
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
    db: AsyncSession = Depends(get_db),
) -> IngestFilesResponse:
    """`POST /api/ingest/files` (ingest-files-api).

    See the module docstring for why `program_id` and auth are resolved
    manually rather than via a declarative `Depends(get_ingest_token)`,
    why the envelope-`kind` check runs before auth, and why the org
    rebuild is scheduled via `BackgroundTasks` (D-01 / ADR-0012).
    """
    try:
        payload: Any = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="request body is not valid JSON",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="request body must be a JSON object",
        )

    program_id = payload.get("program_id")
    if not isinstance(program_id, str) or not program_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="program_id is required",
        )

    # FR-7 / AC-4 abort tier: envelope `kind` not in `_ACCEPTED_KINDS` ->
    # 400 with zero writes. Checked BEFORE auth to match api.md's
    # ordering ("Router-tier check, before auth"). `payload.get("kind")`
    # may be `None` or a non-string; `accept_envelope_kind` treats any
    # non-accepted value as reject and never raises.
    kind = payload.get("kind")
    if not isinstance(kind, str) or not accept_envelope_kind(kind):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown envelope kind",
        )

    # Auth + program-scope (401/403) -- full reuse of get_ingest_token,
    # direct call rather than Depends() (see module docstring).
    ingest_token = await get_ingest_token(
        program_id=program_id, credentials=credentials, session=db
    )

    # AC-4 -- 413 on oversized batch, checked AFTER auth so an
    # unauthenticated caller cannot use payload size to probe scope.
    # Non-list `rows` (or missing) is not a router-tier concern; the
    # service layer validates row shape and empty batches are legal.
    raw_rows = payload.get("rows")
    if isinstance(raw_rows, list) and len(raw_rows) > _ENVELOPE_ROW_CAP:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="rows exceed the 5000-entry cap",
        )

    # D-01 / ADR-0012 -- schedule the org rebuild out-of-band. The
    # service invokes this callable once after commit + program rebuild;
    # `background_tasks.add_task` merely queues the coroutine, no I/O
    # happens on this line.
    return await ingest_files(
        db=db,
        program_id=program_id,
        payload=payload,
        token_label=ingest_token.label,
        on_org_rebuild=lambda: background_tasks.add_task(dispatch_org_rebuild),
    )
