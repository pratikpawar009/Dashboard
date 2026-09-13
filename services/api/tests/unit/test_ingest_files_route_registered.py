"""Boot smoke for `POST /api/ingest/files` -- ING-02-FR-6, gap #2, T-12 / F-17.

Follows the `test_auth_oidc_login.py:184` / `test_auth_logout.py:199` precedent
verbatim: boot the real `create_app` app factory via the D-07 `build_app`
fixture (`tests/conftest.py`) and inspect `app.routes` with
`getattr(route, "path", None)` -- never a throwaway local app.

Scope: this file asserts only that the router is mounted at the right path
with the right method. Request/response behaviour (auth denial, envelope
validation, idempotency, PII log redaction, alias mapping, chunk ceiling,
intra-batch dedup, perf) belongs to sibling task test files, not here.

C-5 note: `app/api/ingest.py` (the pre-ING-02 unregistered stub) was deleted
in T-06. The third test guards against a future re-add of a bare `/api/ingest`
route silently shadowing the `/api/ingest/files` prefix mount.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.routing import APIRoute


def test_ingest_files_route_registered(
    build_app: Callable[..., FastAPI],
) -> None:
    app = build_app()
    assert isinstance(app, FastAPI)
    assert any(
        getattr(route, "path", None) == "/api/ingest/files" for route in app.routes
    )


def test_ingest_files_route_method_is_post(
    build_app: Callable[..., FastAPI],
) -> None:
    app = build_app()
    for route in app.routes:
        if getattr(route, "path", None) == "/api/ingest/files" and isinstance(
            route, APIRoute
        ):
            assert "POST" in route.methods, (
                f"expected POST on /api/ingest/files, got {route.methods}"
            )
            return
    raise AssertionError("route /api/ingest/files not found on app.routes")


def test_old_ingest_stub_route_absent(
    build_app: Callable[..., FastAPI],
) -> None:
    """C-5: the deleted `app/api/ingest.py` stub had prefix `/api/ingest`
    (no `/files` suffix). Guard against a future re-add shadowing the
    ING-02 mount."""
    app = build_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/ingest" not in paths, (
        f"pre-ING-02 stub route /api/ingest is registered again: {paths}"
    )
