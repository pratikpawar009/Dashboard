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
from app.core.rbac import org_access, program_visibility
from app.models.rollup import OrgSummaryRollup, ProgramSummary
from app.schemas.org_summary import OrgSummaryCard, OrgSummaryResponse, ProgramsUsingAi
from app.schemas.program_detail import (
    ProgramDetailHeader,
    ProgramDetailResponse,
    ProgramSummaryCard,
)
from app.services.freshness import FreshnessAccessor
from app.services.rollup_compute import compute_adoption_percent
from app.utils.format import format_number

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/overview", tags=["overview"])

_NOT_FOUND_DETAIL = "program not found"
_ORG_ID = "org-1"

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


# DECISIONS.md D-01/D-02 (corrected 2026-09-10): fixed (glyph, label) presentation constants,
# mockup order -- order is part of the contract. The ratio lives on card 1
# (`programs_using_ai`), NOT card 5 (`repos_with_harness_installed_over_total`, a plain count)
# -- an earlier FR-1 revision had this backwards; see `_build_org_summary_cards` below.
_ORG_SUMMARY_GLYPHS_LABELS: tuple[tuple[str, str], ...] = (
    ("▦", "Programs using AI SDLC"),
    ("⬡", "Total token consumption"),
    ("</>", "Lines of code generated by Harness"),
    ("⤴", "Releases using Harness"),
    ("❯", "Repos with Harness installed"),
)


def get_freshness_accessor() -> FreshnessAccessor:
    """FastAPI dependency yielding the ingestion-freshness accessor.

    Exists so the accessor is **overridable** rather than constructed inline.
    `FreshnessAccessor` was always injectable (`__init__(*, session_factory=...)`,
    "Injectable so tests can point the read at a disposable test database"), but
    the handler used to call the bare `FreshnessAccessor()`, which defaults to
    `app/services/freshness.py`'s module-level `SessionLocal` -- bound to
    `settings.database_url` at import, i.e. the real dev database. A test that
    seeded or omitted a `system_metadata` row in its own database therefore had
    no influence on what the freshness read observed, which made the AC-7/FR-3
    tests silently unsound. Two workers hit that independently and reached for
    two *different* monkeypatches; this dependency retires both, via the same
    `app.dependency_overrides` mechanism the tests already use for `get_db`
    (BED-05-style flag OVW-01 AF-04, accepted at triage 2026-09-10).

    Still constructed per request, so R-04's accepted per-request cache-miss
    trade-off is unchanged -- this only makes the construction site swappable.
    """
    return FreshnessAccessor()


def _programs_using_ai(row: OrgSummaryRollup | None) -> ProgramsUsingAi:
    """Raw adoption counts, shared by card 1 and the adoption-indicator region (OVW-01-FR-1).

    `row is None` (AC-2 -- `org_summary_rollup` absent, fresh/never-ingested org) is the
    all-zero fallback: `count=0, total=0, adoption_percent=None`. Research Condition 2:
    `adoption_percent` is `None`, never `0.0`, both here and for a real row whose
    `programs_total == 0` -- `compute_adoption_percent` (api-conventions, BED-02) already
    encodes that rule; this function never re-derives it.
    """
    if row is None:
        return ProgramsUsingAi(count=0, total=0, adoption_percent=None)
    computed = compute_adoption_percent(row)
    return ProgramsUsingAi(
        count=computed["programs_using_ai_count"],
        total=computed["programs_total"],
        adoption_percent=computed["adoption_percent"],
    )


def _build_org_summary_cards(
    programs_using_ai: ProgramsUsingAi, row: OrgSummaryRollup | None
) -> list[OrgSummaryCard]:
    """Map `row` (or the AC-2 all-zero fallback when `row is None`) onto the 5 fixed,
    mockup-ordered cards (DECISIONS.md D-01/D-02, OVW-01-FR-1).

    Card 1 (`programs_using_ai`) is the literal ratio `"{count} / {total}"`, EXEMPT from
    `format_number()` -- the opposite of an earlier FR-1 revision that put `format_number()`
    on card 1 and the ratio on card 5. Card 5 (`repos_with_harness_installed_over_total`) is
    a plain `format_number()` count, not a ratio, despite its `..._over_total` metric id --
    the id is inherited verbatim from AC-1's own enumeration and is not renamed; the mockup
    governs the rendering, not the id. Cards 2-5 always ship `sub=None`; card 1's `sub` is
    `f"{round(adoption_percent)}% adoption"`, or `None` when `adoption_percent is None`
    (`programs_total == 0`) -- the mockup's `sc-if` guard omits the element in that case.
    """
    card1_sub = (
        f"{round(programs_using_ai.adoption_percent)}% adoption"
        if programs_using_ai.adoption_percent is not None
        else None
    )
    total_tokens = row.total_token_consumption if row is not None else 0
    lines_of_code = row.lines_of_code_generated if row is not None else 0
    releases = row.releases_using_harness if row is not None else 0
    repos_installed = row.repos_with_harness_installed if row is not None else 0

    values = (
        f"{programs_using_ai.count} / {programs_using_ai.total}",
        format_number(total_tokens),
        format_number(lines_of_code),
        format_number(releases),
        format_number(repos_installed),
    )
    subs: tuple[str | None, ...] = (card1_sub, None, None, None, None)
    return [
        OrgSummaryCard(glyph=glyph, value=value, label=label, sub=sub)
        for (glyph, label), value, sub in zip(_ORG_SUMMARY_GLYPHS_LABELS, values, subs, strict=True)
    ]


@router.get("/summary", response_model=OrgSummaryResponse)
async def get_org_summary(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    freshness: FreshnessAccessor = Depends(get_freshness_accessor),
) -> OrgSummaryResponse:
    """Return the 5 org-wide summary cards + adoption data (OVW-01-FR-1/FR-3).

    Step order below is a requirement, not a style choice (FR-3):

    1. `org_access(current_user)` -- cio-only gate (AC-3). Raises `HTTPException(403)` with
       no data body for every other persona before anything below runs; also emits
       `rbac_check_org_access` (user_id, persona, an `authorized`/`denied` outcome, and a
       timestamp -- AC-8, inherited from `rbac-checks`/AUTH-03, no new logging code here).
       AUTH-03's own security review is still open (`security: null`) though this
       implementation is shipped and validated (`impl: complete`, `review: PASS`) -- a
       caveat this docstring carries into the PR body, not a merge blocker (research
       Condition 1, `PLAN.md` § Carry-Forward Risks R-01).
    2. `freshness.get_last_successful_run()` -- the accessor arrives via the
       `get_freshness_accessor` dependency (overridable in tests; see its own
       docstring), still constructed fresh per request, not
       an `app.state` singleton (`freshness-api`'s own contract note: each consumer
       owns/shares its instance), so this route's 300s TTL cache never warms across
       requests -- accepted (R-04, MED, no task addresses it).

       This call is UNCONDITIONED by the `org_summary_rollup` lookup in step 3 below: it
       always runs, whether or not a rollup row exists. Its
       `HTTPException(500, "ingestion job may not have run yet")` therefore propagates even
       on a genuinely fresh database where BOTH the `system_metadata` and
       `org_summary_rollup` rows are absent together (`OVW-01-TC-04`) -- it is never masked
       by step 3's all-zero fallback. AC-2 (missing rollup -> all-zero 200) and AC-7
       (missing freshness row -> 500) are independent preconditions on two different
       tables, both reachable from the same never-ingested database; ordering the
       freshness read first is what keeps AC-7's "clear error, not a silent/empty state"
       true in that overlap.
    3. `select(OrgSummaryRollup).where(org_id == "org-1")` -- row absent (AC-2) yields the
       all-zero envelope (`_programs_using_ai`/`_build_org_summary_cards` both special-case
       `row is None`); row present computes real values via `compute_adoption_percent`.

    Nothing above ever renders on `/overview`: AC-6 is backend-only -- the freshness read
    exists purely for its error/observability behaviour, and no field of its return value
    (a `datetime`) reaches this function's response model or any client. Do not add a
    freshness/as-of timestamp to the UI or this response on the strength of this call
    existing -- `REQUIREMENTS.md` settled that 2026-09-09 and it is not reopened here.
    """
    # AC-3/AC-8: cio-only gate; raises before any read below on denial (no data body).
    await org_access(current_user)

    # FR-3: unconditioned by the rollup lookup below -- see docstring step 2 above.
    await freshness.get_last_successful_run()

    stmt = select(OrgSummaryRollup).where(OrgSummaryRollup.org_id == _ORG_ID)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    programs_using_ai = _programs_using_ai(row)
    cards = _build_org_summary_cards(programs_using_ai, row)

    return OrgSummaryResponse(cards=cards, programs_using_ai=programs_using_ai)
