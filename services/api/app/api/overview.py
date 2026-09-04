"""GET /api/overview/program-detail/{program_id} -- program header + 7-card summary.

Response shape is fixed by ADR-0007 (`docs/adr/0007-program-detail-response-shape.md`) and
`docs/requirements/api.md#program-detail-api`: `{header: {icon, name, type, description},
summary: [{glyph, value, label}, ...]}` -- see `app/schemas/program_detail.py`. `header` is
verbatim `program_summary` data (DECISIONS.md D-05): no `avatarStyle`/`typeChip` on the wire --
consumers derive those client-side via `apps/web/src/lib/programStyle.ts::getProgramStyle(type)`,
matching the already-shipped `persona-shell`/`program_context` convention. `summary` is exactly 7
entries in mockup order with glyph/label as fixed presentation constants owned by this module
(DECISIONS.md D-06); `value` is the only field that varies per program -- cards 1/2/3/5/6/7 pass
through `format_number()`, card 4 is the literal ratio string `"{repos} / {repos_total}"`, exempt
from that formatter (PGD-01-FR-2).

FR-PD-17/AC-6 -- zero persona branching: the response body is byte-identical for every persona
that can successfully authenticate. No field here is conditioned on `current_user.role`, persona,
or `current_user.programs`.

FR-1/C-3 -- `program_visibility` veto gate: called here exactly ONCE, with the REAL `program_id`
from the path (unlike `app/api/programs.py`'s sentinel-argument call, which has no per-resource id
to pass). It is an open-aggregate check (AUTH-03 D-03) that passes for any authenticated session
regardless of `program_id` -- a passing call is a session-validity probe, not proof of program
membership (PGD-01 Clarification C-3: this endpoint is intentionally unscoped; only the
switcher's `GET /api/programs` list is membership-scoped, upstream, in AUTH-04). Downstream
consumers must never treat this endpoint's `200` as evidence of program membership, and this
handler never filters by `current_user.programs`.

AUTH-04 `href` dependency: the frontend's "Switch program" selector navigates using
`GET /api/programs`'s `href` field, which AUTH-04 emits as `f"/programs/{program_id}"`
(DECISIONS.md D-04) -- this router does not itself read that field, but its own route path is the
navigation target that fix depends on for the switcher's in-place reload (FR-4) to work at all.

D-07 -- `program_switch` vs `program_drilldown`: the optional `X-Program-Switch-From` request
header distinguishes a switcher-triggered reload from an initial page load. Present and
non-empty -> logs `program_switch {from_program_id, to_program_id}`; absent (or empty) -> logs
`program_drilldown {program_id}`. Exactly one of the two fires, and only on the 200 path below --
never on the 404 path.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_db
from app.core.rbac import program_visibility
from app.models.rollup import ProgramSummary
from app.schemas.program_detail import (
    ProgramDetailHeader,
    ProgramDetailResponse,
    ProgramSummaryCard,
)
from app.utils.format import format_number

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/overview", tags=["overview"])

_NOT_FOUND_DETAIL = "program not found"

# ADR-0007/DECISIONS.md D-06: fixed (glyph, label) presentation constants, mockup order -- order
# is part of the contract. Zipped below with the row's own values; never re-derived, relabeled, or
# reordered by any consumer.
_SUMMARY_CARD_GLYPHS_LABELS: tuple[tuple[str, str], ...] = (
    ("⬡", "Token consumption"),
    ("✦", "Features delivered via Harness"),
    ("⤴", "Releases done via Harness"),
    ("❯", "Repos with Harness installed"),
    ("›_", "Commands executed"),
    ("</>", "Lines of code generated"),
    ("≡", "User stories delivered"),
)


def _build_summary(row: ProgramSummary) -> list[ProgramSummaryCard]:
    """Map `row`'s 7 metric columns onto the fixed, mockup-ordered card list (ADR-0007).

    Card 4 (repos-with-Harness-installed) is the literal ratio string, exempt from
    `format_number()` (PGD-01-FR-2); the other 6 all pass through it.
    """
    values = (
        format_number(row.tokens),
        format_number(row.features),
        format_number(row.releases),
        f"{row.repos_with_harness_installed} / {row.repos_total}",
        format_number(row.commands_executed),
        format_number(row.lines_of_code_generated),
        format_number(row.user_stories_delivered),
    )
    return [
        ProgramSummaryCard(glyph=glyph, value=value, label=label)
        for (glyph, label), value in zip(_SUMMARY_CARD_GLYPHS_LABELS, values, strict=True)
    ]


@router.get("/program-detail/{program_id}", response_model=ProgramDetailResponse)
async def get_program_detail(
    program_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_program_switch_from: str | None = Header(alias="X-Program-Switch-From", default=None),
) -> ProgramDetailResponse:
    """Return `program_id`'s header + 7-card summary, or 404 if it doesn't exist.

    See the module docstring for the veto-gate (FR-1), byte-identical-across-personas invariant
    (FR-PD-17/AC-6), and `program_switch`/`program_drilldown` event semantics (D-07).
    """
    # FR-1/C-3: open-aggregate veto gate, called once, with the REAL program_id -- see module
    # docstring. Never filters by `current_user.programs`.
    await program_visibility(current_user, program_id)

    stmt = select(ProgramSummary).where(ProgramSummary.program_id == program_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)

    response = ProgramDetailResponse(
        header=ProgramDetailHeader(
            icon=row.icon,
            name=row.name,
            type=row.type,
            description=row.description,
        ),
        summary=_build_summary(row),
    )

    # D-07: exactly one of the two events below, only on this 200 path -- never on the 404
    # raised above. No PII: both events carry only opaque program ids.
    if x_program_switch_from:
        logger.info(
            "program_switch",
            extra={"from_program_id": x_program_switch_from, "to_program_id": program_id},
        )
    else:
        logger.info("program_drilldown", extra={"program_id": program_id})

    return response
