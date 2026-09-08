"""Role-slug -> dashboard-role mapping (ING-10-FR-3; DECISIONS.md D-03).

In-process, `ING-10`-scoped only -- a plain module-level lookup table, not a
DB-backed table. Research risk #3 floated a shared `role_mapping` table so
`ING-08`'s Keycloak writer could eventually reuse it; the PRD/RTM accepted
the in-process-only scope as an author assumption rather than a fresh
confirmation, so wiring `ING-08` onto a shared table stays an undecided
scope change to an already-shipped story and is not built here (see
PLAN.md S6, carried-forward risk `R-03-role-map-persistence`).

Single consumer in this pass: `app.services.manifest_ingest` classifies an
unmapped slug as a row-level rejection (D-09), never a request-level abort
and never a silent default -- a fabricated default would grant a real
person the wrong dashboard scope.
"""

# dev/arch/pm/em map 1:1 to their own persona. `cxo` and `board_member` fold
# onto "cio" -- both are unambiguously executive titles, and persona-resolver's
# vocabulary has only 5 values (auth.md#persona-resolver), so a fold is
# unavoidable; FR-SH-20 sets the precedent of resolving extra executive-role
# slugs to "cio".
#
# `admin` is DELIBERATELY ABSENT (AF-01, triaged 2026-09-08). It used to fold
# onto "cio" too, which was a privilege grant: "cio" bypasses program scoping
# entirely (`/api/programs` returns every program for it), and a roster slug is
# whatever a program's own committed `.harness/program.yaml` says -- reviewed
# only by that program's PR reviewers. That let a program grant org-wide
# dashboard visibility from inside its own repo.
#
# The Keycloak path already made the same call: when
# `services/api/config/persona_role_map.yaml` was populated in PR #235,
# `admin: cio` was omitted on purpose, with the committed reasoning that
# "mapping a broad IdP role such as `admin` to `cio` would hand org-wide
# visibility to that role, which is a decision for whoever owns the realm."
# The roster path is arguably the more sensitive of the two, so it now matches.
#
# Consequence: `map_role_slug("admin")` returns None, which the caller turns
# into a row-level rejection with a reason (fail-closed, grants nothing) rather
# than silently assigning a persona. Do not re-add it without a decision on the
# record -- see DECISIONS.md D-03.
_ROLE_SLUG_TO_PERSONA: dict[str, str] = {
    "dev": "developer",
    "arch": "architect",
    "pm": "product-manager",
    "em": "engineering-manager",
    "cxo": "cio",
    "board_member": "cio",
}


def map_role_slug(slug: str) -> str | None:
    """Return the long-form dashboard role for a roster `slug`, or `None`.

    `None` means the slug is not one of the mapped roster roles (`dev`,
    `arch`, `pm`, `em`, `cxo`, `board_member`, `admin`). The caller turns
    that into a row-level rejection with a reason (D-09) -- this function
    never raises and never substitutes a default role.
    """
    return _ROLE_SLUG_TO_PERSONA.get(slug)
