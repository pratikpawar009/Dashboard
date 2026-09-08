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
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_db
from app.core.rbac import individual_usage_visibility
from app.dependencies.range import validate_range
from app.schemas.personal_usage import PersonalUsageResponse
from app.services.personal_usage import (
    fetch_card_totals,
    fetch_commands_breakdown,
    fetch_daily_token_series,
)

router = APIRouter(prefix="/api/personal-usage", tags=["personal-usage"])


def _range_with_default(request: Request, range: str = Query("30d")) -> str:
    """DECISIONS.md D-02 / Condition C-3: supplies only the `Query` default.

    Delegates the `{7d,30d,90d}` membership check, the `HTTP 400` rejection, and the
    `invalid_range` warning log entirely to the shared `validate_range` -- `app/dependencies/
    range.py` is never edited by this story.
    """
    return validate_range(request, range)


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
