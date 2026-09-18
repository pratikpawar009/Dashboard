"""GET /api/personal-usage/{user_id} -- personal usage cards + daily token chart + commands.

Response shape is fixed by ADR-0009 (`docs/adr/0009-personal-usage-api-response-shape.md`) and
`docs/requirements/api.md#personal-usage-api`: `{cards, daily_tokens, commands}` -- see
`app/schemas/personal_usage.py`. `cards` is a to-date aggregate (unbounded by `range`);
`daily_tokens`/`commands` are range-scoped. No `program_id` anywhere -- "my usage" is a
cross-program aggregate by contract.

FR-1 (AC-1) -- `cards` is exactly 4 order-locked entries with the full 5-key shape
(`glyph, value, label, iconBg, iconColor`, no `delta`), built by `app.services.personal_usage
.fetch_card_totals`.

FR-2 (AC-2) -- `daily_tokens` is a raw `{points, period_total, avg_per_day}` numeric series, one
zero-padded point per day in the selected range, built by `fetch_daily_token_series`.

FR-3 (AC-3) -- `commands[].barStyle` is max-of-range (`count / max(counts) * 100`), not
share-of-total, built by `fetch_commands_breakdown` via `app.utils.format.bar_style_for_share`.

FR-4 (AC-4) -- RBAC denial is a bare `HTTPException(403)` (no data body), raised by
`individual_usage_visibility` (self always, else `cio`) and rendered by the existing
`app/core/errors.py` handler as `{"error": {"code": "http_403", "message": "Forbidden",
"details": null}}`. `individual_view_denied` is logged by that check itself on every denial
(NFR-011) -- this router makes a single, bare call and does not wrap it in try/except.

FR-5 -- `avg_tokens_per_session` is `0.0`, never `None`, for a user with zero sessions
(`app.services.rollup_compute.compute_average`'s own contract, consumed unchanged here).

FR-6 (AC-5, DECISIONS.md D-02) -- `range` defaults to `30d` when omitted via the story-local
`_range_with_default` wrapper below, which supplies ONLY the `Query` default. The `{7d,30d,90d}`
membership check, the `HTTP 400` rejection, and the `invalid_range` warning log all stay inside
the shared `app.dependencies.range.validate_range`, unedited (Condition C-3) -- FastAPI resolves
`Depends()` parameters before the handler body runs, so an invalid `range` on a cross-user
request 400s before `individual_usage_visibility` is ever evaluated.

--- SHP-03: GET /{user_id}/sessions ---

SHP-03-FR-1 (AC-1) -- `PersonalSessionsResponse` envelope (`items`, `page`, `page_size`, `total`),
built by `app.services.personal_usage.fetch_sessions_paginated`. Each `items[]` entry is a
`PersonalSessionEntry` with exactly 4 pre-formatted string fields (`title`, `meta`, `duration`,
`tokens`) -- `meta` is a server-composed `"S-<identifier> · <Mon Day, YYYY>"` composite, never
shipped as two separate raw fields (DECISIONS.md D-03). `duration`/`tokens` are pre-formatted via
`format_session_duration`/`format_session_tokens`; the service layer owns both, not this route.

SHP-03-FR-2 -- rows are ordered `started_at DESC, id ASC` inside `fetch_sessions_paginated`. The
`id` tiebreak is required because `started_at` is not guaranteed unique across sessions --
`LIMIT/OFFSET` pagination without a fully deterministic ORDER BY can return duplicate or skipped
rows across page boundaries (research risk R-02). This route does not re-specify the ordering; it
is entirely the service function's responsibility.

SHP-03-FR-3 (DECISIONS.md, REQUIREMENTS.md § Open questions) -- `page_size` defaults to `20`, NOT
the shared `get_page_params` dependency's own default of `MAX_PAGE_SIZE` (100), via the
story-local `_sessions_page_params` wrapper below -- same override shape as `_range_with_default`
above, supplying only the `Query` default and delegating all bounds/clamp logic to the shared
dependency. `app/dependencies/pagination.py` is a sealed cross-story contract (BED-02 D-01) and is
NEVER edited here. A `page_size` above `MAX_PAGE_SIZE=100` is CLAMPED to 100 by `get_page_params`,
never rejected with `HTTP 400` -- this deliberately contradicts the SHP-03 story's own AC-3 text
("returns `HTTP 400`"), which REQUIREMENTS.md documents as a stale/incorrect story assumption
(PRD FR-3, PO-approved with the correction outstanding). Do NOT "fix" this to a 400 check --
`page < 1` / `page_size < 1` still 422 via the dependency's `ge=1` bounds, which is the only
rejection path that exists here.

SHP-03-FR-4 (AC-4, DECISIONS.md D-04) -- identical RBAC gate and denial-logging shape as
`get_personal_usage` above: `individual_usage_visibility(current_user, user_id)` is called bare,
first statement, no try/except. R-03 (research risk register): the gate logs
`individual_view_denied` on denial only and logs nothing on authorization -- this asymmetric,
denial-only logging is INTENTIONAL (AUTH-03-FR-2 precedent, SHP-04-FR-2 precedent), not a bug to
"balance" with an added authorized-access log line.
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_db
from app.core.rbac import individual_usage_visibility
from app.dependencies.pagination import get_page_params
from app.dependencies.range import validate_range
from app.schemas.personal_sessions import PersonalSessionsResponse
from app.schemas.personal_usage import PersonalUsageResponse
from app.services.personal_usage import (
    fetch_card_totals,
    fetch_commands_breakdown,
    fetch_daily_token_series,
    fetch_sessions_paginated,
)

router = APIRouter(prefix="/api/personal-usage", tags=["personal-usage"])


def _range_with_default(request: Request, range: str = Query("30d")) -> str:
    """DECISIONS.md D-02 / Condition C-3: supplies only the `Query` default.

    Delegates the `{7d,30d,90d}` membership check, the `HTTP 400` rejection, and the
    `invalid_range` warning log entirely to the shared `validate_range` -- `app/dependencies/
    range.py` is never edited by this story.
    """
    return validate_range(request, range)


def _sessions_page_params(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1)
) -> tuple[int, int]:
    """SHP-03-FR-3: supplies only this route's `page_size=20` default (mirrors the mockup's own
    `sesPageSize = 20`).

    Delegates ALL bounds/clamp logic -- including the `page_size > 100` clamp-not-reject
    behavior -- to the shared `get_page_params`, unedited. `app/dependencies/pagination.py` is a
    sealed cross-story contract (BED-02 D-01); this wrapper never duplicates or overrides its
    clamping, it only changes what an omitted `page_size` resolves to before that clamp runs.
    """
    return get_page_params(page, page_size)


@router.get("/{user_id}", response_model=PersonalUsageResponse)
async def get_personal_usage(
    user_id: str,
    range: str = Depends(_range_with_default),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonalUsageResponse:
    """Return `user_id`'s usage cards, daily token chart, and commands breakdown.

    See the module docstring for the RBAC gate (FR-4), the default-range wrapper (FR-6), and the
    to-date-vs-ranged split (ADR-0009).
    """
    # FR-4/AC-4: bare call -- the check itself raises HTTPException(403) and logs
    # individual_view_denied on denial (self always, else cio). No try/except here.
    await individual_usage_visibility(current_user, user_id)

    cards = await fetch_card_totals(db, user_id)
    daily_tokens = await fetch_daily_token_series(db, user_id, range)
    commands = await fetch_commands_breakdown(db, user_id, range)

    return PersonalUsageResponse(cards=cards, daily_tokens=daily_tokens, commands=commands)


@router.get("/{user_id}/sessions", response_model=PersonalSessionsResponse)
async def get_personal_sessions(
    user_id: str,
    page_params: tuple[int, int] = Depends(_sessions_page_params),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonalSessionsResponse:
    """Return `user_id`'s paginated session-wise usage list (SHP-03-FR-1).

    See the module docstring's "SHP-03" section for the RBAC gate (FR-4), the `page_size=20`
    default wrapper (FR-3), and the `meta`-composite / ordering contracts (FR-1/FR-2) owned by
    `fetch_sessions_paginated`.
    """
    # SHP-03-FR-4: bare call -- the check itself raises HTTPException(403) and logs
    # individual_view_denied on denial only (self always, else cio). No try/except here.
    await individual_usage_visibility(current_user, user_id)

    page, page_size = page_params
    return await fetch_sessions_paginated(db, user_id, page, page_size)
