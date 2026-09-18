"""GET /api/artifacts/{program_id} -- 5-row fixed-order artifact counts panel.

Response shape is fixed by `SHP-04-FR-1` and `docs/requirements/api.md#artifacts-api`:
`{items: [{tag, name, count, bg, color}, ...]}` -- see `app/schemas/artifacts.py`. `items` is
always exactly 5 entries in `_CANONICAL_ARTIFACT_TYPES` order; a program with no
`program_artifacts` rows still returns all 5 at `count: 0` (AC-3), built by
`app.services.artifacts.fetch_program_artifacts`.

FR-2/D-01 (`governance_visibility` is this gate's first live route consumer) -- `architect`,
`product-manager`, `developer` are authorized; `cio` and `engineering-manager` are denied. The
route adds ZERO logging of its own around the gate call: `governance_visibility`
(`app/core/rbac.py:196-243`) already logs `rbac_check_governance_visibility` with an `outcome`
field on both the authorized and denied paths, and raises `HTTPException(403)` itself before any
`program_artifacts` read -- matching the no-additional-logging precedent in
`personal_usage.py`/`overview.py`. Do NOT add a `governance_view_denied` event; the story's
Decision-log entry naming one is superseded by `REQUIREMENTS.md` SHP-04-FR-2.

FR-3/D-02 -- `governance_visibility(current_user, program_id)` is wired as a bare `await` inside
the handler body (NOT a `Depends()`), mirroring `personal_usage.py`'s `individual_usage_visibility`
call exactly -- the persona check runs FIRST, before any data read, so a denial returns a bodyless
403 with no artifact data. Only after the persona gate passes does it cascade into
`program_visibility` (open-aggregate: any authenticated session, no per-program membership filter)
-- an unknown `program_id` is therefore never rejected by the gate itself; it falls through to
`fetch_program_artifacts`'s zero-fill and returns a 200 with all 5 counts at 0. There is no
dedicated 404 path for this endpoint.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_db
from app.core.rbac import governance_visibility
from app.schemas.artifacts import ArtifactsResponse
from app.services.artifacts import fetch_program_artifacts

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("/{program_id}", response_model=ArtifactsResponse)
async def get_program_artifacts(
    program_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArtifactsResponse:
    """Return `program_id`'s 5 canonical artifact-type counts, zero-filled (AC-3).

    See the module docstring for the RBAC gate (FR-2/D-01) and the gate-cascade behaviour
    (FR-3/D-02): `governance_visibility` runs first and unconditionally; only a passing persona
    check cascades into the open-aggregate `program_visibility`, so an unknown `program_id` is
    never 404'd here -- it resolves to an all-zero `ArtifactsResponse` instead.
    """
    # FR-2/D-01: bare call, first statement -- the check itself raises HTTPException(403) and
    # logs rbac_check_governance_visibility (outcome=denied) on denial. No try/except, no
    # additional logging here -- this is governance_visibility's first live route consumer.
    await governance_visibility(current_user, program_id)

    return await fetch_program_artifacts(db, program_id)
