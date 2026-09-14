"""Generic router for `POST /api/ingest/{kind}` (ingest-files-api +
ingest-artifacts-api; ADR-0012, ADR-0013, ING-03 D-01 / D-04).

Wire contracts (frozen):

- `docs/requirements/api.md#ingest-files-api` -- kind="activity" ->
  URL `POST /api/ingest/activity` (was `POST /api/ingest/files` under
  ING-02; the URL was retired in ING-03 D-01 / ADR-0013).
- `docs/requirements/api.md#ingest-artifacts-api` -- kind="artifacts" ->
  URL `POST /api/ingest/artifacts`.

Both responses share the shape `int + int + list[RejectionEntry]` --
`IngestFilesResponse` for activity, `IngestArtifactsResponse` for
artifacts (ING-03 D-02 / Q-02).

The router is a single generic handler on the `/api/ingest` prefix
dispatched by the `{kind}` path-param. `_ACCEPTED_KINDS`
(`app/core/ingest_kind.py`) is the single vocabulary owner; a
path-param regex constraint would fork it and re-introduce the drift
ING-02 D-03 was fighting.

**Byte-for-byte semantics preservation for kind="activity"**
(ADR-0013 § Consequences): the request-tier order for the activity
branch is preserved verbatim from ING-02's shipped
`POST /api/ingest/files`:

  parse JSON -> dict check -> program_id str check ->
  envelope-kind check (400) -> get_ingest_token (401/403) ->
  len(rows) > 5000 (413) ->
  activity_ingest.ingest_files(..., on_org_rebuild=lambda:
      background_tasks.add_task(dispatch_org_rebuild))
  -- ADR-0012 background dispatch UNCHANGED.

The artifacts branch (kind="artifacts") shares parse / dict / program_id
/ envelope-kind / bearer-auth steps, then binds `ArtifactCountsIn` (400
on non-canonical `counts` keys, `kind` mismatch, or missing fields per
ING-03 FR-2) and calls `ingest_artifacts(db, program_id, model.counts,
model.as_of, ingest_token.label)`. NO `background_tasks.add_task(...)`
on the artifacts path (D-03 / ADR-0012 non-applicability).

Auth wiring mirrors `app/api/manifest.py` verbatim (ING-02 FR-5 / C-4):
the envelope's `program_id` lives in the JSON body, not path/query, and
`get_ingest_token`'s own `program_id: str` parameter has no `Path`/`Query`
annotation -- `Depends()` would bind it as a required query parameter
this contract does not accept. So the body is parsed first, `program_id`
read off the raw dict, and `get_ingest_token()` is called directly as a
coroutine (not via `Depends()`), passing that same `program_id` plus a
locally-resolved `credentials`/`session`. This is full reuse of the
dependency's 401 (missing/unknown/revoked/expired) and 403 (scope)
logic, only the calling convention differs; no denial branch is
re-implemented here. `_http_bearer` below is a fresh
`HTTPBearer(auto_error=False)` instance mirroring `ingest_auth.py`'s
own construction -- that module's own instance is private and never
imported (ING-02 FR-6 structural isolation).

PII (`.claude/rules/security-baseline.md`, ING-02 FR-8 / C-7 + ING-03
FR-5): this router never logs any request field. The single
`ingest_write_completed` event lives in `activity_ingest.py`; the
single `ingest_artifacts_write` event lives in `ingest_artifacts.py`;
auth denials are logged inside `ingest_auth.py`. No `email`, `user`,
`command`, `feature`, `session_id`, `token_hash`, or raw body is written
to any logger at any level here.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.ingest_auth import get_ingest_token
from app.core.ingest_kind import accept_envelope_kind
from app.schemas.ingest_artifacts import ArtifactCountsIn, IngestArtifactsResponse
from app.schemas.ingest_files import IngestFilesResponse
from app.services.activity_ingest import dispatch_org_rebuild, ingest_files
from app.services.ingest_artifacts import ingest_artifacts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

# Fresh instance -- see module docstring (ING-02 FR-6). Never import
# `ingest_auth._http_bearer`.
_http_bearer = HTTPBearer(auto_error=False)

# ING-02-AC-4 -- envelope row cap enforced at the router tier before any
# DB work on the activity branch. `activity_ingest._ENVELOPE_ROW_CAP`
# mirrors this constant as defence-in-depth (activity_ingest.py module
# docstring, api.md#ingest-files-api § limits). Preserved byte-for-byte
# from ING-02's shipped router per ADR-0013.
_ENVELOPE_ROW_CAP = 5_000


@router.post("/{kind}", status_code=status.HTTP_200_OK)
async def push_ingest(
    kind: str,
    request: Request,
    background_tasks: BackgroundTasks,
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
    db: AsyncSession = Depends(get_db),
) -> IngestFilesResponse | IngestArtifactsResponse:
    """Generic `POST /api/ingest/{kind}` (ADR-0013 -- single handler).

    See the module docstring for why `program_id` and auth are resolved
    manually rather than via a declarative `Depends(get_ingest_token)`,
    why the envelope-`kind` check runs before auth (ING-02 FR-7 /
    ING-03 FR-1), and why the org rebuild is scheduled via
    `BackgroundTasks` for `kind="activity"` (D-01 / ADR-0012) but NOT
    for `kind="artifacts"` (D-03 / ADR-0012 non-applicability).

    Request-tier order (identical for both kinds up to the auth line;
    diverges after):

      parse JSON -> dict check -> program_id str check ->
      envelope-kind check (URL path `{kind}` + body `kind`, both against
      `_ACCEPTED_KINDS`; the two must agree) ->
      `get_ingest_token(...)` (401/403) -> dispatch by kind.
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

    # ING-02 FR-7 / AC-4 + ING-03 FR-1: envelope `kind` not in
    # `_ACCEPTED_KINDS` -> 400 with zero writes. Checked BEFORE auth to
    # match api.md's ordering ("Router-tier check, before auth"). The
    # URL path-param `kind` is authoritative; the body's `kind` MUST
    # agree with it. `accept_envelope_kind` treats any non-accepted
    # value as reject and never raises.
    body_kind = payload.get("kind")
    if not accept_envelope_kind(kind):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown envelope kind",
        )
    if not isinstance(body_kind, str) or body_kind != kind:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown envelope kind",
        )

    # Auth + program-scope (401/403) -- full reuse of get_ingest_token,
    # direct call rather than Depends() (see module docstring).
    ingest_token = await get_ingest_token(
        program_id=program_id, credentials=credentials, session=db
    )

    if kind == "activity":
        # ING-02 AC-4 -- 413 on oversized batch, checked AFTER auth so
        # an unauthenticated caller cannot use payload size to probe
        # scope. Non-list `rows` (or missing) is not a router-tier
        # concern; the service layer validates row shape and empty
        # batches are legal. Preserved byte-for-byte from ING-02's
        # shipped router per ADR-0013.
        raw_rows = payload.get("rows")
        if isinstance(raw_rows, list) and len(raw_rows) > _ENVELOPE_ROW_CAP:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="rows exceed the 5000-entry cap",
            )

        # D-01 / ADR-0012 -- schedule the org rebuild out-of-band. The
        # service invokes this callable once after commit + program
        # rebuild; `background_tasks.add_task` merely queues the
        # coroutine, no I/O happens on this line.
        return await ingest_files(
            db=db,
            program_id=program_id,
            payload=payload,
            token_label=ingest_token.label,
            on_org_rebuild=lambda: background_tasks.add_task(dispatch_org_rebuild),
        )

    # kind == "artifacts" -- FR-2 canonical-type validation, D-03 no
    # background dispatch. `_ACCEPTED_KINDS` == {"activity", "artifacts"}
    # today; a future third kind must add its dispatch branch here (an
    # accepted-but-unhandled kind is a silent 500 -- see ingest_kind
    # module docstring).
    try:
        model = ArtifactCountsIn.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid artifacts envelope",
        ) from exc

    return await ingest_artifacts(
        db=db,
        program_id=program_id,
        counts=model.counts,
        as_of=model.as_of,
        token_label=ingest_token.label,
    )
