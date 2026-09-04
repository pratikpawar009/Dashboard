# ADR-0007: `program-detail-api` returns an ordered `summary` card array with server-owned glyph/label

- Status: Accepted
- Date: 2026-09-03
- Deciders: pratik.pawar@apexon.com

## Context

PGD-01's `docs/requirements/api.md#program-detail-api` contract (`GET /api/overview/program-detail/{program_id}`)
is a sealed contract: `consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01]`, none of which are built yet.
Per `docs/design/README.md` (Program Detail mockup screen inventory), the Engineering Manager
Dashboard renders this same section "As Program Detail" and the Architect/Developer/Product
Manager Dashboards each render their own "program summary" section too — five stories in total
render the same 7-card grid from this one endpoint.

Two response shapes were considered for the 7 to-date summary cards:

1. **Flat named fields** — `{token_consumption, features_delivered, releases_done, ...}` (the
   naming `docs/test-cases/PGD-01.json` uses for TDD-authoring purposes; that file's own
   `generation_note` explicitly disclaims these as "best-available names ... not a confirmed
   schema"). Self-documenting, order-independent, but pushes each of the 5 consumer stories to
   independently re-derive the mockup's glyph/label/order for every field it renders.
2. **An ordered array of `{glyph, value, label}` cards** — mirrors the mockup's own `sc-for` binding
   over `{{ summary }}` (`Program Detail.html`, DESIGN.md Region 4) exactly, with glyph and label as
   producer-owned presentation constants (the mockup's literal characters `⬡ ✦ ⤴ ❯ ›_ </> ≡` and
   their fixed labels).

`docs/design/README.md` records that these mockups deliberately bind presentation as well as data
(`prog.dotStyle`, `p.avBg`, etc.) — precedent already followed by AUTH-04's `dot_style_for_program`
(shipping a pre-formatted CSS string server-side rather than an icon-name enum the client
re-interprets). CLAUDE.md's design-system rule makes the mockup the authority on response shape
for API/backend stories, not PRD prose.

## Decision

`GET /api/overview/program-detail/{program_id}` returns:

```yaml
header: { icon, name, type, description }
summary: [{ glyph, value, label }, ...]  # exactly 7, mockup order is part of the contract
```

`summary` is an ordered array of 7 `{glyph, value, label}` objects, in the exact mockup order
(tokens, features, releases, repos-ratio, commands, LOC, stories). `glyph` and `label` are fixed
presentation constants owned by `app/api/overview.py`, not stored in `program_summary` and not
derived by any consumer — every one of ARC-01/DEV-01/PMD-01/EMD-01 renders the grid with a plain
`.map()`/`sc-for` over `summary`, with zero per-consumer glyph/label duplication. `value` is the
one field that varies per program: cards 1/2/3/5/6/7 pass through `format_number()`; card 4
(`repos_with_harness_installed`) is the literal ratio string `"{n} / {repos_total}"`, exempt from
that formatter (PGD-01-FR-2).

The `header` object stays data-only (`icon, name, type, description`) — no `avatarStyle`/`typeChip`
fields, a separate decision (PGD-01 DECISIONS.md D-05) that keeps this endpoint consistent with the
already-shipped `persona-shell`/`program_context` convention (SHP-01) rather than the mockup's
literal (but here rejected) `prog.avatarStyle`/`prog.typeChip` bindings.

## Consequences

- Positive: one producer-side source of truth for glyph/label/order — the 5 stories sharing this
  section never re-derive or risk drifting from the mockup's literal characters/labels. A future
  8th summary card is an additive array-length change, not a breaking rename of a flat field set.
- Negative: array position replaces field name as the addressing mechanism — a consumer wanting
  "just the tokens value" reads `summary[0].value`, not `summary.token_consumption`. Order becomes
  load-bearing (DESIGN.md already frames mockup order as contractual, so this is accepted, not
  incidental) and any future card add/remove needs conscious agreement across the same 5 stories.
- Reversible? Medium — no persisted data depends on this shape; changing it means updating this
  Pydantic response model plus every consumer built against it by then. Low cost today (zero
  consumers exist yet); rising cost as ARC-01/DEV-01/PMD-01/EMD-01 land.

## Flagged gaps

- None — `docs/test-cases/PGD-01.json`'s flat field names were explicitly disclaimed by its own
  author as non-authoritative; no story artifact asserts against them as a wire contract.
