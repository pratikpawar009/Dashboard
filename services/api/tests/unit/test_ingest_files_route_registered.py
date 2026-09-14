"""Boot smoke for `POST /api/ingest/{kind}` -- ING-02-FR-6 preserved under
ADR-0013's generic-router topology (was ING-02 T-12 / F-17).

Follows the `test_auth_oidc_login.py:184` / `test_auth_logout.py:199`
precedent verbatim: boot the real `create_app` app factory via the
D-07 `build_app` fixture (`tests/conftest.py`) and inspect `app.routes`
with `getattr(route, "path", None)` -- never a throwaway local app.

Scope: this file asserts only that the generic ingest router is mounted
at the right path with the right method. Request/response behaviour (auth
denial, envelope validation, idempotency, PII log redaction, alias
mapping, chunk ceiling, intra-batch dedup, perf) belongs to sibling task
test files, not here.

ADR-0013: `POST /api/ingest/files` was retired; the generic route pattern
`POST /api/ingest/{kind}` handles both `kind="activity"` (URL
`/api/ingest/activity`) and `kind="artifacts"` (URL
`/api/ingest/artifacts`). FastAPI stores the pattern (not any resolved
segment) on `app.routes`. The third test guards against a future re-add
of a bare `/api/ingest` route silently shadowing the prefix mount.
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
        getattr(route, "path", None) == "/api/ingest/{kind}" for route in app.routes
    )


def test_ingest_files_route_method_is_post(
    build_app: Callable[..., FastAPI],
) -> None:
    app = build_app()
    for route in app.routes:
        if getattr(route, "path", None) == "/api/ingest/{kind}" and isinstance(
            route, APIRoute
        ):
            assert "POST" in route.methods, (
                f"expected POST on /api/ingest/{{kind}}, got {route.methods}"
            )
            return
    raise AssertionError("route /api/ingest/{kind} not found on app.routes")


def test_old_ingest_stub_route_absent(
    build_app: Callable[..., FastAPI],
) -> None:
    """C-5: the deleted pre-ING-02 `app/api/ingest.py` stub had prefix
    `/api/ingest` (no `/files` or `/{kind}` suffix). Guard against a
    future re-add shadowing the ADR-0013 mount."""
    app = build_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/ingest" not in paths, (
        f"pre-ING-02 stub route /api/ingest is registered again: {paths}"
    )
