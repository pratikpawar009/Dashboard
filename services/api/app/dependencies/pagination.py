"""Offset/limit and page/page_size pagination dependencies.

D-01 (docs/features/BED-02/DECISIONS.md): both helpers CLAMP an out-of-range
value to the documented max instead of rejecting it. `Query(..., le=N)` would
raise HTTP 422 on an over-max value, which is the opposite of AC 3/AC 4's
required behaviour — so bounds below declare `ge=` only, and the max is
enforced via `min(value, MAX)` in the function body. Defaults are set to the
max itself so an omitted param also resolves to the documented max.
"""

from fastapi import Query

MAX_OFFSET_LIMIT = 50
MAX_PAGE_SIZE = 100  # kept equal to app.api.activities.MAX_PAGE_SIZE (TC-08)


def get_offset_limit(
    offset: int = Query(0, ge=0),
    limit: int = Query(MAX_OFFSET_LIMIT, ge=1),
) -> tuple[int, int]:
    """Resolve (offset, limit), clamping limit to MAX_OFFSET_LIMIT (AC 3)."""
    return offset, min(limit, MAX_OFFSET_LIMIT)


def get_page_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(MAX_PAGE_SIZE, ge=1),
) -> tuple[int, int]:
    """Resolve (page, page_size), clamping page_size to MAX_PAGE_SIZE (AC 4)."""
    return page, min(page_size, MAX_PAGE_SIZE)
