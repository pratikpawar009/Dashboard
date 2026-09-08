"""Router for `POST /api/ingest/manifest` (program-manifest-api, ADR-0010, D-02).

Wire contract (frozen): `docs/requirements/api.md#program-manifest-api` --
`{programId, program:{name,type,description}, team:[{email,name,role,aliases[]}]}`.
Success is `200` with a `ManifestResponse` body, not `201` -- see the story
Decision log 2026-09-08 ("Success response code `200` (AC-3) -- assumption,
per `ING-02`/`ING-03` sibling precedent") and `PLAN.md` § Module hierarchy
(`output: 200 ManifestResponse | 400 | 401 | 403 | 413`).

D-02: this is its own dedicated router, never `app/api/ingest.py`'s
unregistered stub -- see that module's docstring / `app/main.py`'s comment
for why that one stays untouched (`ING-02`'s scope, not this story's).

AF-06 (raised by T-06, `app/services/manifest_ingest.py`): the request body
is handed to `ingest_manifest()` as the raw parsed JSON dict, never a
constructed `ManifestIn`. Binding the body to `ManifestIn` here would make
FastAPI validate the *entire* payload -- including every `team[]` entry's
email, via `TeamMemberIn`'s raising `field_validator` -- before this handler
ever ran, turning one malformed email anywhere in `team[]` into a
request-wide `422` and silently breaking D-09/AC-6 (a bad email must reject
only its own entry; every sibling entry and the identity write still
commit). `request.json()` is the only body access this module performs, and
the resulting dict is passed to `ingest_manifest()` unchanged.

`program_id` resolution -- deliberately **not** a declarative
`Depends(get_ingest_token)` wire-up. `program-manifest-api`'s frozen shape
carries `programId` only in the JSON body; `get_ingest_token`'s own
`program_id: str` parameter (`app/core/ingest_auth.py`) has no `Path`/`Query`
annotation, so FastAPI would otherwise bind it as a REQUIRED QUERY
parameter -- a query string this contract never documents and this endpoint
does not accept. So this handler parses the body first, reads `programId`
off the raw dict, and then calls `get_ingest_token()` directly as a plain
coroutine (not via `Depends()`), passing it that same `program_id` plus a
locally-resolved `credentials`/`session`. This is full reuse of
`get_ingest_token`'s 401 (missing/unknown/revoked/expired) and 403 (scope,
incl. the `"*"` wildcard) logic -- "consume it, do not reimplement any of
it" -- only the calling convention differs from the declarative form; no
denial branch is duplicated here. `_http_bearer` below is a fresh
`HTTPBearer(auto_error=False)` instance mirroring `ingest_auth.py`'s own
construction (that module's own instance, `_http_bearer`, is private --
leading underscore -- and is never imported; FR-6 there already requires
structural isolation from any other bearer instance).

`program_id` is then passed to `ingest_manifest()` as its own parameter,
never re-derived from `payload.get("programId")` a second time -- matching
that service's own docstring ("every write below uses this parameter, never
`payload.get('programId')`"): this router resolves `program_id` exactly
once and both the auth-scope check and the eventual write use that single
value.

FR-5/AC-8 -- 413 cap on raw `team[]` entries, pre-alias-expansion, exact
threshold **500** (`docs/features/ING-10/REQUIREMENTS.md` FR-5: "`team[]`
raw entry count, counted before alias expansion, greater than 500 -> `413`
returned before any row is parsed or written"; `docs/stories/ING-10.md`
Decision log 2026-09-08 confirms the same number). Checked here, after auth
but before `ingest_manifest()` is ever called, so an oversized payload is
rejected at the trust boundary without paying for that call's Tier-1/Tier-2
validation cost. `manifest_ingest.py` also carries its own internal
`_TEAM_ENTRY_CAP` check (same 500, same detail) -- that duplication is
`.claude/rules/security-baseline.md`'s "re-validate at the service layer as
defence-in-depth" in practice, not dead code to remove: it still protects
any future direct caller of `ingest_manifest()` that bypasses this router
(e.g. a later MCP/CLI transport -- `ING-04`/`ING-06` -- deliberately
deferred, `docs/requirements/api.md#program-manifest-api` `consumed_by: []`).

This router's cap check short-circuits before `ingest_manifest()` runs, so a
real oversized HTTP request never reaches the service's own 413 logging
branch. That was originally left as a flagged observation (`AF-09`) and it
meant an operator saw NO `ingest_manifest_write` at all for a rejected
oversized push, while FR-2 documented that the event fires on every outcome.

`AF-09` was triaged `accept` on 2026-09-08 and fixed: this router now emits
the event itself on its 413 branch (see the cap check below), calling the
SHARED `log_ingest_manifest_write` -- promoted from private in
`manifest_ingest.py` precisely so FR-2's field allowlist has one
implementation rather than two copies to drift apart. The values mirror the
service's own 413 branch exactly, so the two layers are indistinguishable in
the log stream. The service's branch remains reachable by a direct caller.

PII (`.claude/rules/security-baseline.md`, R-01): the only thing this router
logs is that one FR-2-allowlisted event -- no `email`, `name` or raw body is
written to any logger at any level here, and
`test_over_cap_http_emits_ingest_manifest_write_af09` asserts the emitted
record carries neither the synthetic email nor the name it was fed.
`_log_ingest_token_auth_failed` stays entirely inside `ingest_auth.py`.
"""

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.ingest_auth import get_ingest_token
from app.schemas.manifest import ManifestResponse
from app.services.manifest_ingest import (
    elapsed_ms,
    ingest_manifest,
    log_ingest_manifest_write,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["ingest-manifest"])

# Fresh instance -- see module docstring. Never import ingest_auth.py's own
# (private) `_http_bearer`.
_http_bearer = HTTPBearer(auto_error=False)

# FR-5/AC-8: raw team[] entry count, counted BEFORE alias expansion. Mirrors
# manifest_ingest.py's own `_TEAM_ENTRY_CAP` (private there, not imported --
# see module docstring for why both layers carry this constant).
_TEAM_ENTRY_CAP = 500


@router.post("/manifest", status_code=status.HTTP_200_OK, response_model=ManifestResponse)
async def push_manifest(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
    db: AsyncSession = Depends(get_db),
) -> ManifestResponse:
    """`POST /api/ingest/manifest` (program-manifest-api).

    See the module docstring for why `program_id` and auth are resolved
    manually rather than via a declarative `Depends(get_ingest_token)`, and
    why the FR-5 cap check lives here rather than inside `ingest_manifest()`.
    """
    start = time.perf_counter()
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

    program_id = payload.get("programId")
    if not isinstance(program_id, str) or not program_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="programId is required",
        )

    # Auth + program-scope (401/403) -- full reuse of get_ingest_token, see
    # module docstring for why this is a direct call rather than Depends().
    ingest_token = await get_ingest_token(
        program_id=program_id, credentials=credentials, session=db
    )

    # FR-5/AC-8: reject an oversized team[] before ingest_manifest() ever
    # runs -- see module docstring on ordering + defence-in-depth.
    raw_team = payload.get("team")
    if isinstance(raw_team, list) and len(raw_team) > _TEAM_ENTRY_CAP:
        # AF-09 (triaged 2026-09-08): emit the event HERE too. This branch
        # short-circuits before ingest_manifest() runs, so the service's own
        # 413 log branch is unreachable over HTTP -- without this, an operator
        # would see no `ingest_manifest_write` at all for a rejected oversized
        # push, and FR-2's "logs on every outcome" promise would hold only for
        # a direct service caller. Values mirror the service's 413 branch
        # exactly (identity_written=False, roster_received=the count we saw,
        # every other counter 0) so the two layers are indistinguishable in
        # the log stream. The emitter is shared, not duplicated, so FR-2's
        # field allowlist has a single implementation.
        log_ingest_manifest_write(
            program_id=program_id,
            token_label=ingest_token.label,
            identity_written=False,
            roster_received=len(raw_team),
            roster_valid=0,
            roster_created=0,
            roster_updated=0,
            roster_removed=0,
            roster_rejected=0,
            duration_ms=elapsed_ms(start),
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="team exceeds the 500-entry cap",
        )

    return await ingest_manifest(
        db=db,
        program_id=program_id,
        payload=payload,
        token_label=ingest_token.label,
    )
