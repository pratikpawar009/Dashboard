"""Public export surface for `app.dependencies` — range + pagination Depends()
helpers.

Callers (routers) import from `app.dependencies` without knowing the internal
file grouping (pagination.py / range.py). `pagination.MAX_OFFSET_LIMIT` and
`pagination.MAX_PAGE_SIZE` are deliberately NOT re-exported here:
`MAX_PAGE_SIZE` shares its name with `app.api.activities.MAX_PAGE_SIZE`
(TC-08 asserts the two are equal, but they remain two distinct constants), so
re-exporting it at package level would make `from app.dependencies import
MAX_PAGE_SIZE` read as though it were the router's own value. Both pagination
constants are left off `__all__` together, for a uniform surface, rather than
re-exporting the unambiguous one and hiding only the colliding one. Callers
that need either constant import it directly from
`app.dependencies.pagination`. `range._RANGE_DAYS` stays private too — only
the two Depends() callables, the page/offset resolvers, and the unambiguous
`ALLOWED_RANGES` constant are re-exported here, per
`.claude/rules/reusability-baseline.md` ("public APIs are intentional").
"""

from app.dependencies.pagination import get_offset_limit, get_page_params
from app.dependencies.range import ALLOWED_RANGES, range_to_start, validate_range

__all__ = [
    "ALLOWED_RANGES",
    "get_offset_limit",
    "get_page_params",
    "range_to_start",
    "validate_range",
]
