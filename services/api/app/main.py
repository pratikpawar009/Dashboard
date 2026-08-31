from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.activities import router as activities_router
from app.api.health import router as health_router
from app.api.ingest import router as ingest_router
from app.auth.dev_bypass import router as dev_bypass_router
from app.auth.jwks import JwksCache
from app.auth.oidc import router as oidc_router
from app.auth.state_store import OAuthStateStore
from app.core import rbac
from app.core.config import Settings, settings
from app.core.db import engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.persona_resolver import PersonaResolver

configure_logging()


def create_app(settings_override: Settings | None = None) -> FastAPI:
    """Assemble the FastAPI app (D-07).

    Takes an optional per-call `Settings` instead of always reading the
    frozen module-level singleton, so a test can boot the app under a
    different config each (ENVIRONMENT, OIDC-completeness, CORS_ORIGINS) with
    no `importlib.reload`. The effective config lands on `app.state.settings`
    / `app.state.jwks_cache` / `app.state.oauth_state_store`, which
    `get_settings` (app/core/config.py), `get_jwks_cache` (app/auth/jwks.py)
    and `get_oauth_state_store` (app/auth/state_store.py) read at request
    time -- every route
    handler must reach config/JWKS through those dependencies, never the
    module singleton or a module-global cache, or a test's override is
    silently ignored (D-07 / D-07 addendum).
    """
    cfg = settings_override or settings
    app = FastAPI(title=cfg.app_name)
    app.state.settings = cfg
    app.state.jwks_cache = JwksCache(cfg)
    app.state.oauth_state_store = OAuthStateStore()
    # D-07: constructed synchronously, no try/except -- a missing/malformed
    # Tier-2 YAML raises uncaught, failing `create_app()` at import time so
    # Uvicorn's own process-exit-on-import-failure is the fail-fast behavior.
    app.state.persona_resolver = PersonaResolver(cfg)
    # AUTH-03 D-06: rbac.py's five checks reach the resolver via this
    # module-level seam (the locked rbac-checks contract has no
    # Request/resolver parameter to thread it through) -- must run
    # immediately after the line above, or every persona-resolving check
    # raises RuntimeError at first call.
    rbac.configure(app.state.persona_resolver)

    register_exception_handlers(app)

    # Middleware ordering: Starlette places `app.add_middleware(...)` entries
    # between its own ServerErrorMiddleware (outermost -- backs the catch-all
    # `Exception` handler `register_exception_handlers` just registered above)
    # and its ExceptionMiddleware (innermost -- backs the StarletteHTTPException
    # / RequestValidationError handlers). So CORSMiddleware wraps routing +
    # ExceptionMiddleware but sits inside ServerErrorMiddleware. Consequence:
    # every raised HTTPException response (FR-2's 501, a 422 validation error,
    # a 404 from an unregistered route) passes back out through CORSMiddleware
    # and gets CORS headers same as a success response, and an OPTIONS
    # preflight is answered by CORSMiddleware itself before routing/exception
    # handling ever runs (TC-11/TC-25). The one response CORSMiddleware can't
    # reach is a genuinely unhandled exception rendered directly by
    # ServerErrorMiddleware (the 500 "internal_error" body) -- a documented
    # Starlette/FastAPI limitation of any single-CORSMiddleware setup, not
    # something register-order here introduces or could avoid; FR-9 doesn't
    # ask for that guarantee.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(health_router)
    app.include_router(ingest_router)
    app.include_router(activities_router)
    app.include_router(oidc_router)  # FR-2 gates at request time (501) -- always registered
    if cfg.dev_bypass_enabled:  # D-01 fail-closed allow-list, never a `!=` deny-check
        app.include_router(dev_bypass_router)

    # `on_event` is deprecated in this FastAPI version (already emitted in the
    # test suite before this task). Migrating to a lifespan handler is out of
    # scope here (surgical-changes): the only change this task makes is
    # moving the existing hook inside the factory, unchanged otherwise, so
    # every app instance disposes the shared engine on its own shutdown.
    @app.on_event("shutdown")
    async def _dispose_engine() -> None:
        await engine.dispose()

    return app


app = create_app()
