"""Unit tests for app/dependencies/pagination.py — BED-02-TC-05..08.

Both pagination helpers declare `Query(...)` defaults (FastAPI query-parsing
descriptors). Calling them as bare Python functions returns those `Query`
objects, not resolved ints, unless every argument is supplied explicitly —
so the "omitted" cases in TC-05/TC-07 would not genuinely exercise FastAPI's
own default resolution if driven that way; they'd only test Python's
argument binding. This module therefore stands up a tiny FastAPI app with
one Depends()-wired throwaway test route per helper (mirroring BED-02-TC-01's
pattern for `validate_range`) and drives it through FastAPI's synchronous
`TestClient`, so every case — omitted, within-bounds, and over-max — goes
through the real `Query()` -> Depends() resolution path. The test app is
defined only in this module and is never wired into production routes
(out of BED-02 scope; see `app/main.py` for the real router assembly).
"""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.activities import MAX_PAGE_SIZE as ACTIVITIES_MAX_PAGE_SIZE
from app.dependencies.pagination import (
    MAX_OFFSET_LIMIT,
    MAX_PAGE_SIZE,
    get_offset_limit,
    get_page_params,
)

app = FastAPI()


@app.get("/test-paginate-offset")
def _offset_route(resolved: tuple[int, int] = Depends(get_offset_limit)) -> dict:
    offset, limit = resolved
    return {"offset": offset, "limit": limit}


@app.get("/test-paginate-page")
def _page_route(resolved: tuple[int, int] = Depends(get_page_params)) -> dict:
    page, page_size = resolved
    return {"page": page, "page_size": page_size}


client = TestClient(app)


# BED-02-TC-05 (AC-3): limit clamps to MAX_OFFSET_LIMIT (50) when omitted or over-max.
def test_offset_limit_clamps_when_omitted() -> None:
    resp = client.get("/test-paginate-offset")
    assert resp.status_code == 200
    assert resp.json()["limit"] == MAX_OFFSET_LIMIT


def test_offset_limit_clamps_when_over_max() -> None:
    resp = client.get("/test-paginate-offset", params={"limit": 500})
    assert resp.status_code == 200
    assert resp.json()["limit"] == MAX_OFFSET_LIMIT


# BED-02-TC-06: within-bounds offset/limit pass through unchanged.
def test_offset_limit_passes_through_within_bounds() -> None:
    resp = client.get("/test-paginate-offset", params={"offset": 10, "limit": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert body["offset"] == 10
    assert body["limit"] == 20


# BED-02-TC-07 (AC-4): page_size clamps to MAX_PAGE_SIZE (100) when omitted or over-max.
def test_page_size_clamps_when_omitted() -> None:
    resp = client.get("/test-paginate-page")
    assert resp.status_code == 200
    assert resp.json()["page_size"] == MAX_PAGE_SIZE


def test_page_size_clamps_when_over_max() -> None:
    resp = client.get("/test-paginate-page", params={"page_size": 250})
    assert resp.status_code == 200
    assert resp.json()["page_size"] == MAX_PAGE_SIZE


# BED-02-TC-08: shared MAX_PAGE_SIZE stays consistent with activities.py's own —
# T-02 deliberately did not import the router's constant (avoids inverting the
# dependency direction), so this equality check is the only thing enforcing it.
def test_max_page_size_matches_activities_router() -> None:
    assert MAX_PAGE_SIZE == ACTIVITIES_MAX_PAGE_SIZE == 100
