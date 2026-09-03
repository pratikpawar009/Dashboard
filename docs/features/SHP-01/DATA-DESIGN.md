# SHP-01 — Data Design

State & data management for the persona header/context shell. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

N/A — no store of any kind. The shell holds no data of its own; every value it renders arrives as a prop from the composing page (ARC-01/DEV-01/PMD-01/EMD-01, none of which are implemented yet). `formatPersonaTag()`'s persona→{tag, subtitle, color, background} map and `programStyle.ts`'s program-type→{color, background} map are hardcoded lookup tables in source (FR-2, FR-4), not a data model — see `docs/design/tokens.md` § Persona colors / § Program type colors for the literal values (D-04, `DECISIONS.md`).

## 2. Migrations

N/A — no schema, no store.

## 3. Ownership & tenancy

N/A — the shell accepts already-scoped props; it performs no lookup of its own, so there is no resource id to own-check. Program/persona/session ownership and scoping are enforced upstream by AUTH-01 (`session`)/AUTH-02 (`persona-resolver`) and by whichever composing page resolves `program` — outside this story's scope (PRD § Scope, "Out").

## 4. Data classification & retention

`signedInUser.name` / `signedInUser.jobTitle` are PII (display name, job title). The shell renders them only — never logs them, never forwards them to analytics or telemetry (NFR-2, NFR-4: this presentational shell emits no telemetry of its own). No retention/deletion concern: nothing is persisted or cached by the shell: it is a pure function of its props, re-rendered from whatever the composing page supplies on each render.

## 5. Consistency & concurrency

N/A — no writes, no shared mutable state, no concurrent-caller scenario. The shell is a pure render of its current props; React's own render model (not this story) governs re-render timing when a prop changes.

## 6. Caching

N/A — no cache. `formatPersonaTag()` and `programStyle.ts`'s lookup are synchronous in-memory map reads (module-level constants), not a cache with a TTL or an invalidating event.

## 7. Ephemeral / session state

N/A beyond the props the shell is handed. The shell holds no client state of its own (no `useState`, no context, no URL param) — Screen inventory pins Render as "server (no client interactivity in MVP)" for all three regions, and no interactivity in this story's scope needs one. The `session` (AUTH-01) and `persona` (AUTH-02) values the composing pages resolve to build the shell's props are that page's own ephemeral/session-state concern, not this story's — see § Contract below and PRD § Scope ("Out": fetching/resolving `session`).

## 8. Query-path & access-path performance

N/A — no I/O. The shell's own render-time budget (≤200ms p95, `SHP-01-NFR-1`) is exercised by `SHP-01-TC-04`; the upstream fetch/resolve time is explicitly owned by the composing pages (PRD § NFR-1), not this component.

## 9. Contract (API / interface)

Registered cross-story contract — concrete shape authored once at the shared registry, this section is a bookmark only:

`Contract: persona-shell → docs/requirements/api.md#persona-shell`

The concrete prop interface (`signedInUser`, `persona`, `program`, and the three render states the shell derives from them) was filled into that shared file during this planning phase, per `plan-authoring` step 10 — replacing its `produced_by`-only decomposition-time sketch (`signed_in_user: { name, role }`) with the shape this plan actually designs. `ARC-01`/`DEV-01`/`PMD-01`/`EMD-01` build against that file, not against this one.

## 10. Async & messaging

N/A — no message, event, or job. The shell performs no I/O and has no writer/reader counterpart.
