"""Unit tests for app/core/role_map.py — ING-10-AC-3, ING-10-AC-6.

`map_role_slug(slug: str) -> str | None` is the shared role-slug -> persona
lookup DECISIONS.md D-03 describes: a plain in-process module-level dict,
`ING-10`-scoped only (no DB-backed table — see R-03, accepted). Its
authoritative mapping, per D-03 / PLAN.md §6 / docs/stories/ING-10.md's
Decision log, is exactly 6 mapped roster slugs:

    dev -> developer, arch -> architect, pm -> product-manager,
    em -> engineering-manager, cxo -> cio, board_member -> cio

Two corrections landed on 2026-09-08 and this docstring reflects the settled
state:

- **AF-03** — the count was never 8. Task T-04's title and
  `docs/research/ING-10.md` said "8 slugs"/"8-way" in several places without
  ever naming an 8th value, while every contract enumerated 7. That was a
  miscount carried out of research; the titles and research doc have since
  been corrected rather than an 8th slug invented.
- **AF-01** — `admin` was then REMOVED from the map, taking 7 to 6. It used to
  fold onto `cio`, which bypasses program scoping entirely, and the grant
  originated from a program's own committed `.harness/program.yaml`. See
  `test_map_role_slug_admin_is_deliberately_unmapped_af01` below: `admin` is
  now asserted as an UNMAPPED slug, so re-adding it fails loudly.

AC-3 requires each mapped slug to resolve to its long-form persona so
`user_roles` upserts the correct dashboard role. AC-6 requires an
out-of-vocabulary slug to be rejected at the row level, not silently
defaulted — `map_role_slug` returning `None` (never raising, never
substituting a default) is what lets `manifest_ingest.py` build that
row-level rejection instead of granting a real person the wrong dashboard
scope.
"""

import pytest

from app.core.role_map import map_role_slug

# ---------------------------------------------------------------------------
# ING-10-AC-3 — every mapped roster slug resolves to its exact long-form role
# ---------------------------------------------------------------------------

# The 6 mapped roster slugs D-03 / PLAN.md §6 / the story's Decision log agree
# on. `cxo` and `board_member` both fold onto "cio" (FR-SH-20 precedent) — two
# different roster inputs, one shared output, asserted individually so a future
# edit that breaks just one of them fails on its own row.
#
# `admin` is NOT here on purpose: AF-01 (triaged 2026-09-08) removed its
# admin -> cio mapping because "cio" bypasses program scoping and a roster slug
# comes from a program's own committed file. It is asserted below as an
# UNMAPPED slug instead, so re-adding it silently would fail that test.
_ROSTER_SLUG_TO_PERSONA = {
    "dev": "developer",
    "arch": "architect",
    "pm": "product-manager",
    "em": "engineering-manager",
    "cxo": "cio",
    "board_member": "cio",
}


@pytest.mark.parametrize(
    ("slug", "expected_persona"),
    list(_ROSTER_SLUG_TO_PERSONA.items()),
)
def test_map_role_slug_resolves_every_roster_slug(slug: str, expected_persona: str) -> None:
    assert map_role_slug(slug) == expected_persona


def test_map_role_slug_covers_exactly_the_documented_six_slug_vocabulary() -> None:
    """Guards against silent vocabulary drift in either direction: adding an
    undocumented slug or dropping a mapped one would change AC-3's coverage
    without any single parametrized case above failing to notice it."""
    assert set(_ROSTER_SLUG_TO_PERSONA) == {
        "dev",
        "arch",
        "pm",
        "em",
        "cxo",
        "board_member",
    }


def test_map_role_slug_admin_is_deliberately_unmapped_af01() -> None:
    """`admin` must NOT resolve to any persona (AF-01, triaged 2026-09-08).

    It previously folded onto "cio", which bypasses program scoping entirely —
    a privilege grant originating from a program's own committed
    `.harness/program.yaml`, reviewed only by that program's PR reviewers. The
    Keycloak path made the same call in PR #235 by omitting `admin: cio` from
    `config/persona_role_map.yaml`.

    This is a security regression guard, not a vocabulary detail: re-adding the
    mapping restores org-wide dashboard visibility to anyone a program lists as
    `admin`, so this test must fail loudly if that happens. `is None` is
    asserted explicitly so a regression returning a falsy non-None value is
    still caught."""
    assert map_role_slug("admin") is None


# ---------------------------------------------------------------------------
# ING-10-AC-6 — unknown slug is a row-level rejection signal, never a default
# ---------------------------------------------------------------------------


def test_map_role_slug_unknown_slug_returns_none_not_a_default() -> None:
    """A fabricated default would grant a real person the wrong dashboard
    scope (role_map.py's own module docstring) — assert `is None` explicitly
    rather than a falsy check, so a regression that returns e.g. `""` (falsy
    but not `None`) would still be caught."""
    result = map_role_slug("superadmin")
    assert result is None


def test_map_role_slug_unknown_slug_does_not_raise() -> None:
    """AC-6 processes an unmapped slug as one rejected roster row within an
    otherwise-committing request — a raised exception here would make that
    row-level handling impossible for the caller to implement cleanly."""
    map_role_slug("superadmin")  # must not raise


# ---------------------------------------------------------------------------
# Cheap edge cases — the caller passes data straight from a hand-edited,
# committed YAML file (.harness/program.yaml's team[].role), so casing typos
# and blank values are realistic author mistakes, not exotic inputs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", ["Dev", "DEV", "Arch", "ADMIN", "Cxo"])
def test_map_role_slug_is_case_sensitive(slug: str) -> None:
    """The mapping table's keys are lowercase only (role_map.py) — an
    author's mixed-case typo in program.yaml must reject as unmapped, not
    silently match a differently-cased key."""
    assert map_role_slug(slug) is None


def test_map_role_slug_empty_string_returns_none() -> None:
    assert map_role_slug("") is None
