"""GET /api/me -- session identity: display name + resolved persona.

Response shape is fixed by `session-identity-api` (`docs/requirements/api.md`):
`{name, persona}` -- see `app/schemas/me.py`. Authentication only, no persona
or membership gate beyond a valid bearer token (AUTH-07-AC-1/AC-5): this
endpoint takes no target-user parameter and can only ever describe the
caller, so there is no `program_visibility`-style veto gate to call, unlike
`app/api/programs.py`.

AC-3/AC-4 -- fail-closed persona resolution: `persona_resolver.resolve(...)`
is wrapped in try/except, catching `PersonaNotFoundError` BEFORE
`PersonaResolutionError` (its own base class -- reversing the order would make
the `PersonaNotFoundError` branch unreachable), mirroring
`app/api/programs.py:87-112`'s catch order exactly. Both branches raise
`HTTPException(403, "Access denied")` -- never a `200` carrying a null or
defaulted `persona`.

AC-5 -- `401` on a missing/invalid bearer token is `get_current_user`'s own
existing behavior; this route introduces no new 401 logic.

AC-7 -- no route-owned cache: every call re-invokes `resolve()`, riding
persona-resolver's own 300s TTL. Adding a cache here would be a second cache
racing the resolver's own, never done.

NFR-Observability -- this route emits NO log event of its own (unlike
`app/api/programs.py`'s `programs_persona_resolution_failed`/
`programs_list_returned`): `persona_resolver.resolve()` already emits
`persona_mapping_loaded` on success and `persona_mapping_not_found` on an
all-tiers-miss (auth.md#persona-resolver `observability`), so a second event
here would duplicate that signal (`.claude/rules/reusability-baseline.md`).
`name` is PII and must never appear in a log line -- there being no event
here at all is the simplest way to keep that invariant.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, get_current_user
from app.core.persona_resolver import (
    PersonaNotFoundError,
    PersonaResolutionError,
    PersonaResolver,
    get_persona_resolver,
)
from app.schemas.me import MeResponse

router = APIRouter(prefix="/api/me", tags=["me"])

_ACCESS_DENIED_DETAIL = "Access denied"


@router.get("", response_model=MeResponse)
async def get_me(
    current_user: CurrentUser = Depends(get_current_user),
    persona_resolver: PersonaResolver = Depends(get_persona_resolver),
) -> MeResponse:
    """Return the caller's display name and resolved persona.

    See the module docstring for the fail-closed persona resolution (AC-3/
    AC-4) and no-route-owned-cache (AC-7) semantics.
    """
    # AC-3/AC-4: `PersonaNotFoundError` is caught before its own base class
    # `PersonaResolutionError`, or the former's branch would be unreachable
    # (mirrors app/api/programs.py). Neither branch logs (see module
    # docstring, NFR-Observability) -- `persona_resolver.resolve()` already
    # emitted its own event before raising.
    try:
        persona = await persona_resolver.resolve(current_user.role)
    except PersonaNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_DETAIL
        ) from None
    except PersonaResolutionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_DETAIL
        ) from None

    # AC-1/AC-3: exact two-field allowlist, persona is the resolver's output
    # verbatim -- MeResponse's `extra="forbid"` also guarantees this at the
    # model layer.
    return MeResponse(name=current_user.name, persona=persona)
