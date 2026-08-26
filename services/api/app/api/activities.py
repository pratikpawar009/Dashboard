"""Synchronous REST reads against Postgres (ADR-0002: Execution model).

Paginated per .claude/rules/performance-baseline.md — every list endpoint has
a bounded default and max page size.
"""

from fastapi import APIRouter, Query

router = APIRouter(prefix="/activities", tags=["activities"])

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@router.get("")
async def list_activities(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> dict:
    # TODO(implementation): query Postgres via SQLAlchemy, apply LIMIT/OFFSET or keyset pagination.
    return {"items": [], "page": page, "page_size": page_size, "total": 0}
