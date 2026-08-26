---
name: requirement-tracing
description: RTM numbering, epic→story hierarchy, the RTM table schema, the Decisions block, the per-kind contract files, and traceability backlinks. Source-of-truth for requirement IDs.
when_to_use: Decomposing a requirement or maintaining docs/requirements/RTM.md.
user-invocable: false
allowed-tools: Read Write Edit Grep
---
# Requirement Tracing

## Numbering

- Epics: `<EPIC>` (3-letter uppercase, e.g. `CHK` for Checkout).
- Stories: `<EPIC>-<NN>` (zero-padded, sequential). A split produces more **sibling**
  stories at this level — never a `.<n>` suffix.
- Tasks: `<EPIC>-<NN>.<MM>`. This suffix is the **task** namespace only.
- Test cases: `<EPIC>-<NN>-TC-<MM>`.

## RTM schema (authoritative)

`docs/requirements/RTM.md` is a title line, then one Markdown table, then one fenced block
(Decisions). Match the columns and order exactly — the author step reads rows positionally.
The RTM traces requirements; it does **not** store contract specs. Shared interfaces are
authored in per-kind files `docs/requirements/<kind>.md` (see § Contracts), and the RTM's
`Contract` column is a pointer to them.

### Hierarchy

The RTM is the **project-wide index** and holds **one or more epics**. Each epic is a row
with `Type: Epic`; its stories are rows with `Type: Story` and `Parent` set to the epic id.
A single intake source may yield more than one epic. Re-runs reconcile new epics into the
same file — never duplicate an existing id.

### File header + table

The RTM opens with a header line, then the table:

```markdown
# Requirements Traceability Matrix
Source hash: e565d65b3d9e   <!-- sha256 of the intake input; drift detection; VCS-independent -->

| ID | Title | Type | Parent | Pri | Size | Depends-on | Contract | Source | Tracker | Status |
|----|-------|------|--------|-----|------|------------|----------|--------|---------|--------|
| CHK | Checkout | Epic | — | — | — | — | — | specs/checkout.md | ACME-100 | — |
| CHK-01 | Apply promo code | Story | CHK | P1 | M | — | cart | specs/checkout.md | ACME-142 | draft |
```

`Source hash` is a header line — the machine drift-check — kept **out** of the table so the
`Source` column stays a plain human label.

A multi-upstream story lists its dependencies **index-aligned**, e.g. `Depends-on = AUTH-01,
CART-02` with `Contract = session, cart` — `AUTH-01` is built against `session`, `CART-02`
against `cart`. Every `Depends-on` id names the interface it consumes.

- **ID** — epic `<EPIC>`; story `<EPIC>-<NN>`.
- **Type** — `Epic | Story`.
- **Parent** — a Story's epic id; `—` on an Epic row.
- **Pri / Size / Depends-on / Contract** — Story rows only; `—` on Epic rows. `Depends-on`
  and `Contract` are **comma-separated lists** when a story has several upstreams — one
  `Contract` entry per `Depends-on` id (index-aligned), so every dependency names the
  interface it is built against.
- **Source** — the intake input this row came from: a doc path (`specs/checkout.md`),
  `raw text`, or a Confluence page (`confluence:<page>`). Same value across one intake run.
  (A row imported from a tracker via `/arh-import` carries the tracker key instead, e.g.
  `jira:ACME-77`.) The drift hash of that input lives in the header line, not here.
- **Tracker** — the issue key created by issue-tracker sync (Step 5), e.g. `ACME-142`; `—`
  before sync or in local mode. Epic rows carry the Epic issue key. Distinct from `Source`
  (where the requirement came *from*) — `Tracker` is the issue this project *created* for it.
  This is external data, so it is stored (unlike derived fields, which are not).
- **Status** — Story: `draft | validated | escalated | imported:<source>`; Epic: `—`.

Independence is **derived**, not stored (see [[requirement-validation]]): `Depends-on = —` →
independent; otherwise independent once **every** `Depends-on` id has its paired `Contract`
frozen. A `Depends-on` entry with no matching `Contract` is a code dependency — a
decomposition failure, not an independent story.

**Build order (waves) is also derived, never stored.** `Depends-on` is the single source of
truth for ordering. A story is buildable once all its `Depends-on` are done; stories with no
dependency between them build in parallel. Any consumer that needs the wave plan computes it
on demand as `1 + max(depth of Depends-on)` — do not persist a "level"/"wave" column, or it
drifts out of sync with the graph (the same reason independence is not stored).

### Contracts (authored in `docs/requirements/<kind>.md`, not the RTM)

A shared interface is **not** stored in the RTM — the RTM only *points* at it via the
`Contract` column. Each interface is authored as a section in a per-kind file
`docs/requirements/<kind>.md`, where `<kind>` is the interface family: `api`, `data`, `auth`,
`event`. `<kind>` is the **filename** — derived from location, never a stored field, the same
discipline as unstored build waves. Create a `<kind>.md` only when a contract of that kind
exists.

One `### <name>` section per contract; markdown header, then a `yaml` block:

````markdown
# docs/requirements/api.md

### promo-redeem-http
```yaml
produced_by: PRM-02
consumed_by: [PRM-03]          # may span epics
shape:
  endpoint: "POST /api/v1/promo-codes/redeem"   # a SKETCH at decomposition
```
````

At decomposition nobody builds yet — the `shape` is a **sketch**, just enough to establish the
seam so the graph can treat producer and consumer as parallelizable once the contract freezes.
The `produced_by` story fills the concrete spec when it plans and implements, and is
responsible for keeping that section matching the shipped surface. The **consuming story builds
against that filled section — later, in its own implement phase — never against the producer's
code.**

**The two views must agree.** A contract section's `consumed_by` list and the story rows are
the same graph seen from two sides — reconcile them. Every id in a `consumed_by` list MUST
name that contract in its own RTM row's `Contract` column and its producer in `Depends-on`
(index-aligned); and every `Contract` entry on a story row MUST resolve to a `### <name>`
section under `docs/requirements/*.md`. A contract consumed in only one place is an
under-declared dependency edge; a `### <name>` section with **no `produced_by`** story is a
phantom contract — both are silent-traceability defects this schema exists to prevent.

### Decisions block

Best-judgment resolutions recorded when a decomposition unknown could not be asked (see
[[story-decomposition]]).

```yaml
## Decisions
- 2026-05-01 session storage: httpOnly cookie (best judgment — no user available)
```

## Backlinks

Every story file header includes a `**Source**:` link. The RTM is the authoritative
mapping; agents update it on `/arh-intake`, `/arh-plan-requirements`, `/arh-implement`.
