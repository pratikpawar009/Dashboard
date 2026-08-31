# ADR-0005: `programs-api` returns the switcher list shape

- Status: Accepted
- Date: 2026-08-31
- Deciders: pratik.pawar@apexon.com

## Context

AUTH-04 research raised C-1 (`docs/research/AUTH-04.md` § Clarifications) as a **blocking** open
clarification: the story's AC-5 field set `{program_id, name, icon, type, description}` does not
match what any mockup binds for this endpoint.

The `programs-api` contract (`docs/requirements/api.md`) declared only an endpoint and a scoping
rule — no `fields` key. AC-5's set was synthesized from FR-SH-02 + FR-PD-03/FR-EM-02 prose, not read
off a binding. Two mockups iterate the switcher list and agree on its item shape:

| Mockup | List | Per-item bindings | Placeholders |
|---|---|---|---|
| PGD-01 `Program Detail.html` | `progOptions` | `o.label`, `o.href`, `o.dotStyle`, `o.rowStyle`, `o.current` | `hint-placeholder-count="6"` |
| EMD-01 `Engineering Manager Dashboard.html` | `projOptions` | same five | `hint-placeholder-count="3"` |

Neither list binds `type` or `description`. The story's 5-field set in fact describes the *header*
object of a single program (`prog.name` / `prog.ptype` / `prog.scope`), which is a different
payload. Both those fields are already owned elsewhere and need no new home:
`program-detail-api` § `header (icon, name, type, description)` and `persona-shell` §
`program_context: { icon, name, type, description }`.

CLAUDE.md § Design system makes the mockup — not PRD prose — the authority on response shape, and
`docs/design/README.md` records two decisions the mockups imply: values arrive pre-formatted, and
the templates bind CSS as well as data. Applied literally, that argues for returning all five
bindings. But `current` (which row shows the ✓) and the `rowStyle` it drives depend on which
program is currently being viewed, and this endpoint receives no active-program input. AUTH-01's
`session` contract is explicitly stateless — no server-side session store — so there is no place
for the server to learn it without adding a presentation-only query parameter.

## Decision

`GET /api/programs` returns the fields the switcher list actually binds, and nothing else:

```yaml
fields: { program_id, label, href, dotStyle }
```

- `label` — the display string (the mockup's `o.label`; AC-5's `name` under the binding's name).
- `href` — a ready-to-use link target, derived server-side from `program_id`. Pre-formatted, per
  the README decision.
- `dotStyle` — pre-formatted CSS for the indicator dot (the mockup's `o.dotStyle`; AC-5's `icon`
  is not an icon name or URL here).
- `program_id` — retained alongside `href` as the stable domain identifier that keys
  `program-detail-api`'s path (`GET /api/overview/program-detail/{program_id}`) and the switch/
  routing use FR-PD-03 and FR-EM-02 call for.

Two consequences of that set, decided explicitly:

1. **`type` and `description` leave this endpoint.** They are bound by the program header and the
   persona shell, not the switcher list, and both contracts already carry them. AUTH-04 AC-5 is
   superseded by this ADR on that point.
2. **`current` and `rowStyle` are client-derived.** The switcher compares each item's `href`
   against the current route to mark the active row and style it. These two are the narrow,
   deliberate exception to "values arrive pre-formatted": they are not properties of a program, they
   are properties of *where the user currently is*, which the server does not and should not know.
   The rule is narrowed for route-dependent presentation state only — every field that is a
   property of the program itself still arrives pre-formatted.

## Consequences

- Positive: every field this endpoint returns traces to a binding some mockup consumes — the gap
  that produced C-1 closes at the contract, not just for this story. No new fields are added to any
  other contract; `type`/`description` are already where they are used. The endpoint stays stateless
  and route-agnostic, consistent with AUTH-01's no-server-side-session NFR.
- Negative: `program_id` and `href` are mildly redundant (one derives from the other) — accepted, so
  consumers routing to `program-detail-api` need no string surgery on `href`. The mockup-as-contract
  rule now carries a documented exception, which future stories must not read as general licence:
  it covers route-dependent state only.
- Reversible? Easy — the response model is a single Pydantic schema in the AUTH-04 router with no
  persisted representation. Moving `current`/`rowStyle` server-side later means adding an
  `?active=<slug>` parameter and the fields, additive for existing consumers.

## Flagged gaps

- `docs/stories/AUTH-04.md` AC-5 still names the old field set. Not edited here — the story is
  `Status: Validated` and re-opening it would force re-validation. The PRD carries the corrected
  set with this ADR as its authority; the story edit is carried forward.
- Source of the `dotStyle` value (per-program colour) is not settled by this ADR — whether it comes
  from a `program_summary` column or a server-side palette assignment is an implementation choice
  for `/arh-plan-implementation`.
