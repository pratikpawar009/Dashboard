"""GET /api/programs -- persona-scoped program list for "Switch program" selectors.

Response shape is fixed by ADR-0005 (`docs/adr/0005-programs-api-switcher-shape.md`):
`{program_id, label, href, dotStyle}` -- see `app/schemas/programs.py`. Scoping is
entirely server-side, never a client-supplied filter (AUTH-04 NFR-security): every
row for the `cio` persona, only rows matching `current_user.programs` for every
other persona.

FR-2/C-2 -- `program_visibility` veto gate: `app.core.rbac.program_visibility` is
called here exactly ONCE, with a sentinel `program_id`
(`_VETO_GATE_SENTINEL_PROGRAM_ID` below) that it never reads. It is an
open-aggregate check (AUTH-03 D-03) that passes for any authenticated session --
a passing call is a session-validity probe, not proof of program membership.
Actual scoping is entirely the `WHERE program_id IN current_user.programs` clause
below (or no filter at all for `cio`). Downstream consumers must read
`current_user.programs`/this response body directly and must never treat this
endpoint's `200` as evidence the caller belongs to any specific program.

FR-3/C-3 -- fail-closed persona resolution: `persona_resolver.resolve(...)` is
wrapped in try/except, catching `PersonaNotFoundError` BEFORE
`PersonaResolutionError` (its own base class -- reversing the order would make
the `PersonaNotFoundError` branch unreachable, mirroring `app/core/rbac.py`'s
`_resolve_persona_or_deny`). Both branches log at WARNING and raise
`HTTPException(403, "Access denied")` -- never a 500.

FR-4/C-5 -- missing-program discrepancy: a `program_id` in
`current_user.programs` with no matching `program_summary` row is silently
excluded by the WHERE clause, never raised. On the non-cio path only, when
`returned_count < len(current_user.programs)`, a separate
`programs_missing_from_summary` WARNING is logged for ops investigation -- the
comparison is meaningless on the `cio` path, where `returned_count` is the full
table size, not derived from `current_user.programs`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_db
from app.core.persona_resolver import (
    PersonaNotFoundError,
    PersonaResolutionError,
    PersonaResolver,
    get_persona_resolver,
)
from app.core.rbac import program_visibility
from app.models.rollup import ProgramSummary
from app.schemas.programs import ProgramEntry, ProgramsListResponse
from app.utils.format import dot_style_for_program

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/programs", tags=["programs"])

# FR-2/C-2: sentinel `program_id` for the veto-gate call below.
# `program_visibility` (app/core/rbac.py) is an open-aggregate check that
# deliberately never reads its own `program_id` argument or
# `current_user.programs` -- passing this literal, rather than a real program
# id, makes that fact visible at the call site: this value is provably never
# consulted for scoping, only used to confirm the session itself is valid.
_VETO_GATE_SENTINEL_PROGRAM_ID = "__veto_gate_sentinel__"

_ACCESS_DENIED_DETAIL = "Access denied"


@router.get("", response_model=ProgramsListResponse)
async def list_programs(
    current_user: CurrentUser = Depends(get_current_user),
    persona_resolver: PersonaResolver = Depends(get_persona_resolver),
    db: AsyncSession = Depends(get_db),
) -> ProgramsListResponse:
    """Return the programs `current_user` may see, in switcher-list shape.

    See the module docstring for the veto-gate (FR-2), fail-closed persona
    resolution (FR-3), and missing-program discrepancy (FR-4) semantics.
    """
    # FR-2/C-2: session-validity veto gate, called exactly once, never
    # per-program. See module docstring + `_VETO_GATE_SENTINEL_PROGRAM_ID`.
    await program_visibility(current_user, _VETO_GATE_SENTINEL_PROGRAM_ID)

    # FR-3/C-3: fail-closed persona resolution -- `PersonaNotFoundError` is
    # caught before its own base class `PersonaResolutionError`, or the
    # former's branch would be unreachable (mirrors app/core/rbac.py).
    try:
        persona = await persona_resolver.resolve(current_user.role)
    except PersonaNotFoundError:
        logger.warning(
            "programs_persona_resolution_failed",
            extra={
                "user_id": current_user.user_id,
                "role": current_user.role,
                "reason": "not_found",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_DETAIL
        ) from None
    except PersonaResolutionError:
        logger.warning(
            "programs_persona_resolution_failed",
            extra={
                "user_id": current_user.user_id,
                "role": current_user.role,
                "reason": "resolution_error",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_DETAIL
        ) from None

    # AC-1/AC-2/AC-4: `cio` sees every row; every other persona is scoped to
    # `current_user.programs`. `in_([])` on an empty list already yields zero
    # rows -- no empty-list special case needed; the response is a 200 with
    # `programs: []`.
    if persona == "cio":
        stmt = select(ProgramSummary)
    else:
        stmt = select(ProgramSummary).where(
            ProgramSummary.program_id.in_(current_user.programs)
        )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    # AC-5: map each row to the ADR-0005 switcher shape.
    programs = [
        ProgramEntry(
            program_id=row.program_id,
            label=row.name,
            href=f"/programs/{row.program_id}",
            dotStyle=dot_style_for_program(row.program_id),
        )
        for row in rows
    ]

    # FR-1/C-1: exact 3-field allowlist -- no email, no groups, no request
    # path (TC-09 asserts key-set equality, not a subset).
    logger.info(
        "programs_list_returned",
        extra={
            "user_id": current_user.user_id,
            "persona": persona,
            "returned_count": len(programs),
        },
    )

    # FR-4/C-5: non-cio only -- a `program_id` in `current_user.programs`
    # absent from `program_summary` is already excluded above by the WHERE
    # clause; this just signals the discrepancy for ops, never raises.
    # Meaningless on the cio path (`returned_count` there is the full table
    # size, not derived from `current_user.programs`).
    if persona != "cio" and len(programs) < len(current_user.programs):
        logger.warning(
            "programs_missing_from_summary",
            extra={
                "user_id": current_user.user_id,
                "expected_count": len(current_user.programs),
                "returned_count": len(programs),
            },
        )

    return ProgramsListResponse(programs=programs)
