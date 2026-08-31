"""RBAC check library -- five async authorization checks consumed by 16
downstream stories via the `rbac-checks` contract
(`docs/requirements/auth.md#rbac-checks`). Each check gates on
`CurrentUser` (AUTH-01) and, where relevant, the persona AUTH-02's
`PersonaResolver` resolves from `current_user.role`; a check either
returns `None` (authorized) or raises `fastapi.HTTPException(status_code=403)`
(denied) -- never a bool return, never a 5xx for a denial (AUTH-03-FR-5).

This module ships the module-level `configure()` seam, all five check
functions (`org_access`, `program_visibility`, `individual_usage_visibility`,
`member_in_program_visibility`, `governance_visibility`), and the two shared
private helpers every persona-resolving check reuses:
`_resolve_persona_or_deny` and `_log_event`.

Fail-closed contract (D-01, AUTH-03-FR-1): every call site that resolves
persona catches `PersonaNotFoundError` (routine -- an ordinary unmapped
role, all three of AUTH-02's tiers missed) and `PersonaResolutionError`
(operational failure -- e.g. a Tier-3 Postgres timeout) in two SEPARATE
`except` clauses, never a bare `except Exception`. `PersonaNotFoundError`
is `PersonaResolutionError`'s own subclass, so it must be caught FIRST --
reversing the order would make its INFO-level branch unreachable, since
every `PersonaNotFoundError` instance also satisfies `except
PersonaResolutionError`. Both deny with `HTTPException(403)`; zero
default-permit outcomes, ever. `PersonaResolutionError` additionally logs
the calling check's own event at `logging.ERROR` (an operational failure);
`PersonaNotFoundError` logs at the check's normal `logging.INFO` level (a
routine deny).

`program_visibility` (AC3, D-03) ships the open-aggregate model exactly as
specified -- any authenticated session passes, for any `program_id` value.
It is a VETO GATE, not a roster source: a passing call does not mean the
caller is affirmatively a member of `program_id`. Downstream consumers
needing a roster answer must read `CurrentUser.programs` directly, never
infer membership from this check passing. R-003 (the operational risk this
model carries) stays OPEN, flagged for `/arh-security-review` -- not
accepted or closed by this story (`REQUIREMENTS.md` § Approvals,
2026-08-31).

`_GOVERNANCE_PERSONAS` (D-04, AUTH-03-FR-3) is a plain hardcoded module
constant -- a deliberate contrast with AUTH-02's fully data-driven
resolver: adding a persona to governance access needs a code change and a
redeploy, not a config edit, until a future story promotes it to
`Settings`. Only `governance_visibility` reads it.
"""

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException

from app.core.auth import CurrentUser
from app.core.persona_resolver import (
    PersonaNotFoundError,
    PersonaResolutionError,
    PersonaResolver,
)

logger = logging.getLogger(__name__)

# D-06: process-lifetime, set exactly once by `configure()` -- see
# `_resolver()` below for the loud-failure contract when it's never called.
_persona_resolver: PersonaResolver | None = None

# D-04/AUTH-03-FR-3: hardcoded, not config/DB-driven (see module docstring).
# `cio` and `engineering-manager` are deliberately excluded (AC6).
_GOVERNANCE_PERSONAS: tuple[str, ...] = ("architect", "product-manager", "developer")


def configure(persona_resolver: PersonaResolver) -> None:
    """D-06: called exactly once, by `app.main.create_app()`, immediately
    after constructing the app's `PersonaResolver`. Sets the module-level
    reference every persona-resolving check reads via `_resolver()`.

    This module's own unit tests call this directly with a stub resolver
    before exercising a check -- they never build a FastAPI app -- the same
    direct-module-attribute-assignment idiom
    `tests/unit/test_persona_resolver.py` already uses for
    `_TIER3_TIMEOUT_SECONDS`.
    """
    global _persona_resolver
    _persona_resolver = persona_resolver


async def org_access(current_user: CurrentUser) -> None:
    """AC1/AC2: only the `cio` persona passes; every other persona denies.

    Logs `rbac_check_org_access` on both outcomes (D-02): `outcome=
    "authorized"` when persona == "cio", `outcome="denied"` otherwise --
    including the fail-closed denial routed through
    `_resolve_persona_or_deny` when the resolver itself raises.
    """
    persona = await _resolve_persona_or_deny(current_user, "rbac_check_org_access", {})
    if persona != "cio":
        _log_event("rbac_check_org_access", "denied", user_id=current_user.user_id, persona=persona)
        raise HTTPException(status_code=403)
    _log_event("rbac_check_org_access", "authorized", user_id=current_user.user_id, persona=persona)


async def program_visibility(current_user: CurrentUser, program_id: str) -> None:
    """AC3 (D-03): open-aggregate pass-through -- passes for any
    authenticated session, for any `program_id` value.

    Deliberately does NOT read `current_user.programs` (TC-27 asserts this
    structurally, via a `CurrentUser` test double whose `.programs` raises
    if accessed) and does NOT branch on `program_id` (TC-04). Never resolves
    persona. Emits no log event of its own -- there is no denial branch to
    log (AUTH-03-FR-2's closing note, TC-28).

    See the module docstring: this is a veto gate, not a roster source.
    R-003 stays OPEN, flagged for `/arh-security-review`.
    """
    return None


async def individual_usage_visibility(current_user: CurrentUser, target_user_id: str) -> None:
    """AC4: passes when `target_user_id == current_user.user_id` (self) --
    the self path resolves NO persona at all (TC-05 depends on the resolver
    never being consulted on it). Otherwise passes only for persona ==
    "cio"; every other requester/target combination denies.

    Logs `individual_view_denied` on DENIAL ONLY (D-02/AUTH-03-FR-2 -- unlike
    `org_access`, this check has no "authorized" event to log): both the
    persona-mismatch denial below and the resolver-failure denial routed
    through `_resolve_persona_or_deny` share the same event name and field
    set, `{user_id, target_user_id, outcome, timestamp}`.
    """
    if target_user_id == current_user.user_id:
        return None

    persona = await _resolve_persona_or_deny(
        current_user, "individual_view_denied", {"target_user_id": target_user_id}
    )
    if persona != "cio":
        _log_event(
            "individual_view_denied",
            "denied",
            user_id=current_user.user_id,
            target_user_id=target_user_id,
        )
        raise HTTPException(status_code=403)


async def member_in_program_visibility(
    current_user: CurrentUser, program_id: str, target_member_id: str
) -> None:
    """AC5 (D-03/AUTH-03-FR-4): `program_visibility` runs FIRST, always --
    its denial propagates immediately, before self-or-cio is ever
    evaluated, even when `target_member_id == current_user.user_id` (TC-10
    asserts this exact call ORDER with a spy, not merely the end-to-end
    outcome).

    Deliberate asymmetry with `individual_usage_visibility`: there, the
    self path short-circuits FIRST, before any persona resolution --
    here, the `program_visibility` cascade runs BEFORE the self path. This
    is AUTH-03-FR-4's explicit requirement, not an inconsistency to "fix"
    into symmetry: getting the order backwards still passes a naive
    outcome-only test today (since `program_visibility` never denies under
    D-03's current open-aggregate model), but breaks the contract the
    moment a future story tightens that check.

    Once `program_visibility` passes: passes when `target_member_id ==
    current_user.user_id` (self, no persona resolution); otherwise resolves
    persona via `_resolve_persona_or_deny` and passes only for "cio". Logs
    `member_view_denied` on DENIAL ONLY (D-02) -- same no-authorized-event
    convention as `individual_view_denied`.

    Calls `program_visibility` by its bare module-level name rather than
    qualifying it: a global reference inside a function is looked up via
    the function's `__globals__` (this module's own namespace) at CALL
    time, not bound at definition time -- so a test's
    `monkeypatch.setattr(rbac, "program_visibility", spy)` is seen here
    without needing a `rbac.program_visibility(...)`-qualified call site.
    """
    await program_visibility(current_user, program_id)

    if target_member_id == current_user.user_id:
        return None

    persona = await _resolve_persona_or_deny(
        current_user,
        "member_view_denied",
        {"program_id": program_id, "target_member_id": target_member_id},
    )
    if persona != "cio":
        _log_event(
            "member_view_denied",
            "denied",
            user_id=current_user.user_id,
            program_id=program_id,
            target_member_id=target_member_id,
        )
        raise HTTPException(status_code=403)


async def governance_visibility(current_user: CurrentUser, program_id: str | None = None) -> None:
    """AC6/AC7 (D-04/AUTH-03-FR-4): persona gate FIRST, always -- resolves
    via `_resolve_persona_or_deny` (fail-closed handling applies at this
    call site exactly as it does at `org_access`'s) and passes only when
    `persona in _GOVERNANCE_PERSONAS` (`architect`, `product-manager`,
    `developer`; `cio`/`engineering-manager` excluded, AC6). A persona
    denial raises immediately -- `program_visibility` is NEVER called on
    that path.

    Opposite nesting from `member_in_program_visibility`: there, the
    cascade (`program_visibility`) runs before the self-or-cio persona
    step; here, the persona gate runs before the cascade. Both orders are
    AUTH-03-FR-4's explicit, checked requirement for their respective
    check -- not an inconsistency to "fix" into symmetry.

    Only when the persona gate passed AND `program_id is not None`:
    `program_visibility(current_user, program_id)` also runs, and its
    denial propagates even though persona passed.

    The `authorized` event emits only once the WHOLE check has actually
    passed -- i.e. AFTER the `program_visibility` cascade, never before it
    -- so a call that denies at the cascade step never also emits an
    `authorized` event for itself. Logs `rbac_check_governance_visibility`
    on BOTH outcomes (D-02) -- same allowlist as `org_access`,
    `{user_id, persona, outcome, timestamp}` -- unlike
    `individual_usage_visibility`/`member_in_program_visibility`'s
    denial-only events.
    """
    persona = await _resolve_persona_or_deny(current_user, "rbac_check_governance_visibility", {})
    if persona not in _GOVERNANCE_PERSONAS:
        _log_event(
            "rbac_check_governance_visibility",
            "denied",
            user_id=current_user.user_id,
            persona=persona,
        )
        raise HTTPException(status_code=403)

    if program_id is not None:
        await program_visibility(current_user, program_id)

    _log_event(
        "rbac_check_governance_visibility",
        "authorized",
        user_id=current_user.user_id,
        persona=persona,
    )


# -----------------------------------------------------------------------------
# Private helpers -- no downstream contract, internal to this module only.
# Shared by every persona-resolving check above.
# -----------------------------------------------------------------------------


def _resolver() -> PersonaResolver:
    """Return the configured `PersonaResolver`, or fail loudly (D-06).

    A `RuntimeError` here -- never a silent default-permit -- signals a
    genuine wiring bug: `app.main.create_app()` must call `configure()`
    before any request that reaches a persona-resolving check.
    """
    if _persona_resolver is None:
        raise RuntimeError("rbac.configure() was never called")
    return _persona_resolver


async def _resolve_persona_or_deny(
    current_user: CurrentUser,
    event_name: str,
    extra_fields: dict[str, object],
) -> str:
    """Resolve `current_user.role` to a persona, denying (403) on failure.

    Shared by every persona-resolving check -- `org_access`,
    `individual_usage_visibility`, `member_in_program_visibility`, and
    `governance_visibility` all reuse this unchanged. `extra_fields` carries
    the calling check's own event-specific identifiers already known before
    resolution runs (e.g. `target_user_id`, `program_id`) -- `user_id` is
    always added here, and `persona` is deliberately never included in it,
    since resolution has not produced one yet at the point this denies.

    D-01/AUTH-03-FR-1: `PersonaNotFoundError` (routine, all 3 tiers missed)
    is caught BEFORE `PersonaResolutionError` (its own base class) -- the
    reverse order would make the INFO-level routine-deny branch dead code,
    since every `PersonaNotFoundError` instance also satisfies `except
    PersonaResolutionError`. Never a bare `except Exception`.
    """
    try:
        return await _resolver().resolve(current_user.role)
    except PersonaNotFoundError:
        _log_event(
            event_name,
            "denied",
            level=logging.INFO,
            user_id=current_user.user_id,
            **extra_fields,
        )
        raise HTTPException(status_code=403) from None
    except PersonaResolutionError:
        _log_event(
            event_name,
            "denied",
            level=logging.ERROR,
            user_id=current_user.user_id,
            **extra_fields,
        )
        raise HTTPException(status_code=403) from None


# D-02/AUTH-03-FR-2's four fixed allowlists. `persona` is the one OPTIONAL
# field, on the two `rbac_check_*` events only: present whenever persona
# resolution itself succeeded (an authorized outcome, or a denial reached by
# comparing a successfully-resolved persona), omitted only on the rarer
# denial where resolution itself failed (`_resolve_persona_or_deny`'s two
# `except` branches) and there is no persona value to report -- mirrors
# AUTH-02's own optional `tier3_latency_ms` field
# (`app/core/persona_resolver.py::_log_resolution`). Every other field on
# every event is required.
_EVENT_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "rbac_check_org_access": frozenset({"user_id"}),
    "rbac_check_governance_visibility": frozenset({"user_id"}),
    "individual_view_denied": frozenset({"user_id", "target_user_id"}),
    "member_view_denied": frozenset({"user_id", "program_id", "target_member_id"}),
}
_EVENT_OPTIONAL_FIELDS: dict[str, frozenset[str]] = {
    "rbac_check_org_access": frozenset({"persona"}),
    "rbac_check_governance_visibility": frozenset({"persona"}),
    "individual_view_denied": frozenset(),
    "member_view_denied": frozenset(),
}


def _log_event(
    event_name: str,
    outcome: Literal["authorized", "denied"],
    *,
    level: int = logging.INFO,
    **fields: object,
) -> None:
    """Emit `event_name` at `level`, enforcing D-02/C-2's per-event field
    set (AUTH-03-FR-2) -- the single place every one of the four events
    (`rbac_check_org_access`, `rbac_check_governance_visibility`,
    `individual_view_denied`, `member_view_denied`) is emitted from.

    An unrecognized field, or a missing required one, is a programming
    error (`AssertionError`), not a silently dropped/added field -- see
    `_EVENT_REQUIRED_FIELDS`/`_EVENT_OPTIONAL_FIELDS` above for the
    `persona`-is-optional nuance.

    D-08 (AUTH-02 precedent, still true here): `JSONFormatter` sets its own
    `timestamp` key first and never lets an `extra` value overwrite an
    existing payload key, so the computed `timestamp` below is inert for
    the emitted record -- included anyway per AUTH-03-FR-2's specified call
    shape.
    """
    required = _EVENT_REQUIRED_FIELDS[event_name]
    optional = _EVENT_OPTIONAL_FIELDS[event_name]
    given = set(fields.keys())
    if not required <= given or not given <= (required | optional):
        raise AssertionError(
            f"{event_name}: field set {sorted(given)} does not match "
            f"required {sorted(required)} + optional {sorted(optional)}"
        )
    payload: dict[str, object] = {
        "outcome": outcome,
        "timestamp": datetime.now(UTC).isoformat() + "Z",
        **fields,
    }
    logger.log(level, event_name, extra=payload)
