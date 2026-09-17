# PGD-04 — Decisions

Decision log for Program command activity. Header slugs (`blast:`/`rev:`) are the greppable
half of the record; `plan-validation`'s Decision-promotion dimension reads them.

### D-01: Aggregate from `usage_events`, never `program_commands` · blast:feature · rev:mechanical · adr:—

**Context**: Research R-6/C-4 found `program_commands` (`app/models/rollup.py`) holds
lifetime, unranged counts — `rollup_rebuild.py:246` groups `usage_events` by `command` with no
time filter; `period_start`/`period_end` are `MIN`/`MAX` metadata, not a selectable window.
Reading it for a ranged endpoint would make `?range=` a silent no-op: `7d` and `90d` would
return byte-identical totals while a naive test suite (asserting only `200` + non-empty) stays
green. This is the single highest-risk item in the story.

**Decision**: `fetch_program_commands()` (`app/services/program_commands.py`) queries
`usage_events` directly — `SELECT command, count(*) FROM usage_events WHERE program_id = :pid
AND ts >= :range_start GROUP BY command`, mirroring SHP-02's `_fetch_command_rows` /
`fetch_commands_breakdown` with `WHERE "user" = :user_id` swapped for `WHERE program_id =
:program_id`. Backed by the existing `ix_usage_events_program_id_command` index — no migration
needed. `program_commands` is never imported by this module. Mandatory test: PGD-04-TC-05
(#427) asserts a `7d` and a `90d` request against the same seeded multi-window fixture return
different `total_runs` — the only test in the suite that fails if this decision is violated.

### D-02: Unknown or quiet `program_id` returns `200 {total_runs: "0", items: []}`, never 404 · blast:feature · rev:mechanical · adr:—

**Context**: The sibling `/releases` route 404s on an unknown `program_id` because "this
program's releases" is unanswerable without a `program_summary` row. `/token-trend` instead
zero-fills, because "how much activity in this window" has a true empty answer. Commands
belongs to the second class — a live program with zero in-range command activity is a real,
common state, not an error, and an unknown `program_id` is indistinguishable from that same
empty state without an extra existence lookup this endpoint has no other reason to make.
PGD-02's security review already cleared the analogous no-404 path as not an enumeration
oracle under the same open-aggregate `program_visibility` gate.

**Decision**: The handler performs NO `program_summary` existence lookup. It calls
`program_visibility(current_user, program_id)` once, then always calls
`fetch_program_commands()`, which returns `CommandsPanel(total_runs="0", items=[])` whenever
the `usage_events` aggregation yields zero rows — regardless of whether `program_id` exists
anywhere. This is deliberately inconsistent with `/releases` on the same router; the
inconsistency is principled (see Context) and documented here plus in the route docstring and
README so a future reviewer does not "fix" it into a 404.

### D-03: Reuse `CommandsPanel`/`CommandEntry` from `personal_usage.py`; no `schemas/program_commands.py` · blast:feature · rev:mechanical · adr:—

**Context**: SHP-02's `CommandsPanel { total_runs, items: [{command, count, barStyle}] }`
(`app/schemas/personal_usage.py`) is byte-identical to what PGD-04's AC-1/AC-3 need — same
field names, same `count`-raw-int/`total_runs`-formatted-string asymmetry, same `barStyle`
alias. AC-6 (program vs. personal totals computed independently) is a *computation* constraint,
not a schema-identity one: two callers sharing a response shape does not couple their queries.

**Decision**: Import `CommandsPanel` + `CommandEntry` directly from `app/schemas/
personal_usage.py` into `app/services/program_commands.py` and `app/api/overview.py`. No
`app/schemas/program_commands.py` is created. Add a one-line co-consumer note to
`personal_usage.py`'s module docstring recording PGD-04 as a second consumer of this shape.
Carry-forward: extract a shared `app/schemas/commands.py` only if a third consumer appears —
two consumers importing one module is not yet duplication worth a move.

### D-04: Next.js proxy route ships in this story · blast:feature · rev:mechanical · adr:—

**Context**: REQUIREMENTS.md § Scope lists "Next.js proxy route `/api/proxy/program-detail/
{program_id}/commands` (ADR-0008 pattern, matching PGD-01/02/03's existing proxies)" under
**In**, explicitly distinct from rendering the panel (which is **Out**). The research doc's
Condition #5 framed this as an open question to settle in PLAN.md; REQUIREMENTS.md (Product
Gate APPROVE, 2026-09-17) already settled it before this plan was authored — the proxy is
transport plumbing consumed by a future frontend story, not the panel itself, and every sibling
endpoint on this router (PGD-01/02/03) already ships its proxy in the same story that ships the
backend route, before any component consumes it.

**Decision**: Ship `apps/web/src/app/api/proxy/program-detail/[program_id]/commands/route.ts`
(+ its unit test) in this story, mirroring the token-trend proxy exactly: `callWithAuth`
retry-once, `range` passthrough (absent → `undefined`, not the literal string), 404 handling
kept for type-exhaustiveness even though this endpoint never returns 404 (D-02). A matching
server-only `fetchProgramCommands()` fetcher (`app/lib/programCommandsApi.ts`) and its TS wire
types (`app/types/programCommands.ts`) ship alongside it — the proxy has nothing to call
without them. `CommandsActivity.tsx` (the panel component) is explicitly NOT created (see
REQUIREMENTS.md § Scope) — the proxy has no caller yet and is dead code from the browser's
perspective until a follow-on frontend story lands. This is intentional plumbing-ahead-of-UI,
matching this router's own established shipping order.
