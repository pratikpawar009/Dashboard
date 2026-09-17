# PGD-05 — Decisions

Decision log for Project team table + per-member usage popup. Header slugs (`blast:`/`rev:`)
are the greppable half of the record; `plan-validation`'s Decision-promotion dimension reads
them.

### D-01: Two-SELECT aggregation — `program_members` snapshot + range-scoped `usage_events` aggregate, joined in Python · blast:feature · rev:mechanical · adr:—

**Context**: `program_members` (`app/models/rollup.py::ProgramMembers`) is a to-date snapshot
with no temporal columns and only `ix_program_members_program_id` — it cannot answer a
range-scoped `sessions`/`tokens`/`avg` question on its own (research Risk #1, HIGH). A naive
join to `usage_events` per request risks a full-table scan and a Cartesian product if `GROUP BY`
is mishandled. PGD-05-FR-1 requires exactly two SELECTs, never a join producing duplicate rows.

**Decision**: `fetch_program_team()` (`app/services/program_team.py`) issues exactly two
SELECTs: (1) `SELECT user_id, name, role FROM program_members WHERE program_id = :pid` for the
roster identity fields, and (2) `SELECT "user", SUM(sessions-equivalent), SUM(tokens) FROM
usage_events WHERE program_id = :pid AND ts >= :range_start GROUP BY "user"` for range-scoped
metrics. The two result sets are merged in Python by `user_id`/`user`, never via a SQL join —
this is what keeps the query count bounded at exactly two and avoids any Cartesian product. A
member present in the roster but with zero in-range events is dropped from the response (PGD-05
decision log (a): "active in the selected range"); a member with in-range events but absent from
the roster snapshot (a rebuild-timing edge case) is also dropped — the roster is authoritative
for identity fields (`member_name`, `role`), which the aggregate alone cannot supply.

### D-02: New composite index `(program_id, user, ts)` on `usage_events` · blast:data · rev:medium · adr:ADR-0016

**Context**: Research Condition C-1 (mandatory): the range-scoped aggregate in D-01 filters on
`program_id` + `ts` and groups by `user`. The existing `ix_usage_events_program_id_user`
(no `ts`) and `ix_usage_events_program_id_ts` (no `user`) indexes each cover only two of the
three predicates, forcing a filter or sort step outside the index for this query shape. NFR-002
(≤2s) and the mandatory perf test (exactly two SELECTs, ≤2s) require an index that covers all
three columns together.

**Decision**: New Alembic migration (`008_program_team_index.py`) adds
`Index("ix_usage_events_program_id_user_ts", "program_id", "user", "ts")` on `usage_events`.
This changes a durable, shared table's index set (`blast:data`) — dropping it later is a
`rev:medium` operation (an index drop is reversible without data loss, but requires a
migration + deploy, not a code-only revert) — so per the `decide` promotion rule
(`blast:data`) this is promoted to a full ADR: `docs/adr/0016-usage-events-program-team-index.md`.

### D-03: Popup calls `personal-usage-api` directly from the frontend (ADR-0008 proxy pattern), no PGD-05-owned relay endpoint · blast:feature · rev:mechanical · adr:—

**Context**: Research Condition C-2 / Risk #3 (MED): AC-9 says the popup "calls
`personal-usage-api`" without settling whether PGD-05 adds a relay endpoint on `overview.py` or
the frontend calls SHP-02's endpoint directly through the existing ADR-0008 proxy pattern. AC-10
requires the popup to render SHP-02's response verbatim with no reshaping — a relay endpoint
would add a network hop with zero contract value, since there is nothing for PGD-05 to transform.

**Decision**: The popup's data fetch goes through a new Next.js proxy Route Handler
(`apps/web/src/app/api/proxy/personal-usage/[user_id]/route.ts`), matching PGD-01/02/03's
existing `/api/proxy/program-detail/*` pattern (`callWithAuth` retry-once, status mapping,
ADR-0008) — calling FastAPI's existing `GET /api/personal-usage/{user_id}` directly. PGD-05 adds
no new backend route for this data path; `member_in_program_visibility` (AUTH-03, already
shipped) is enforced server-side by wrapping the existing SHP-02 route call — see D-04.

### D-04: `member_in_program_visibility` enforced via a story-local PGD-05 route, not inside `personal_usage.py` · blast:feature · rev:mechanical · adr:—

**Context**: PGD-05-FR-3 requires the popup's authorization gate to be `member_in_program_visibility`
(`program_visibility` AND (self OR cio)), distinct from and never delegating to SHP-02's own
`individual_usage_visibility` gate on `GET /api/personal-usage/{user_id}` (self always, else cio
only) — the two gates must coexist without either route silently adopting the other's rule.
Editing `personal_usage.py` to accept a second gate would couple SHP-02's contract to PGD-05's
authorization model.

**Decision**: Add a fifth sibling route on the existing `overview` router:
`GET /api/overview/program-detail/{program_id}/team/{member_id}/usage?range=`. This route calls
`member_in_program_visibility(current_user, program_id, member_id)` (already shipped,
`app/core/rbac.py`) and, on success, calls `fetch_personal_usage()` (SHP-02's own service
function, imported directly — not an HTTP call to SHP-02's own route) with `member_id` as the
`user_id`, returning `PersonalUsageResponse` verbatim (AC-10, no reshaping). A denial raises
`HTTPException(403)` before `fetch_personal_usage()` is ever invoked, so a 403 response body
carries no personal-usage fields (AC-12, mutual exclusivity by construction — the function that
produces card/chart/command data is never called on the denied path). This keeps
`personal_usage.py`'s own route and gate completely untouched (zero edits to SHP-02's contract)
while giving the popup one same-origin proxy call to make, per D-03's ADR-0008 pattern, rather
than the frontend needing to know two different backend hosts/gates for one popup.

### D-05: Popup UI (trigger, modal chrome, denied/loading/error states) is design-gated — not planned in this round · blast:feature · rev:mechanical · adr:—

**Context**: REQUIREMENTS.md § Constraints records a hard design gate (Product Gate round 1/2/3,
2026-09-17): AC-9..12's popup has no mockup backing it anywhere — `docs/design/mockups/Program
Detail.html` has no popup, modal, overlay, dialog, or clickable row (DESIGN.md § "The popup is
not in this mockup"), and SHP-02 ships no reusable popup component (`design: "n/a"`, its own PRD
defers all `apps/web` component work). `/arh-iterate-design PGD-05` MUST run and produce the
trigger, modal chrome, and denied(403)/loading/error states before AC-9..12 can be planned or
implemented. Planning speculative UI now would mean inventing a screen, which `CLAUDE.md` §
Design system forbids outright ("If a story seems to need something the mockups do not show,
stop and raise it. Do not design it").

**Decision**: This PLAN ships AC-1..8 (team table endpoint + UI) in full as independently
mergeable, implementable tasks. The popup's backend wiring (D-03/D-04 — the proxy route, the
`member_in_program_visibility`-gated sibling route, and their tests) is planned and IS
implementable now, since none of it requires a visual design decision. The popup's **frontend
component** (row trigger, modal chrome, loading/denied/error rendering) is represented as a
single blocked task (T-16, § 6 below) with an explicit precondition —
`/arh-iterate-design PGD-05` must produce DESIGN.md § Screen 2 content before T-16 can be
started — rather than left as an implicit gap or an invented UI.
