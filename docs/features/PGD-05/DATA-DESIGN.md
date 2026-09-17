# PGD-05 — Data Design

State & data management. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

New index only (no new table/column). Reads two existing tables (Postgres, SQLAlchemy ORM).

### program_members (postgres table, existing — read-only here)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| program_id | str | part of `ix_program_members_program_id` | — | filter predicate |
| user_id | str | — | PII (identifier) | joined against `usage_events."user"` in Python (D-01) |
| name | str | — | PII | sourced verbatim, `member_name` on the wire |
| role | str | — | — | sourced verbatim, `role` on the wire |

### usage_events (postgres table, existing — read-only here; NEW index this story)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| program_id | str | part of NEW `ix_usage_events_program_id_user_ts` | — | filter predicate |
| user | str | part of NEW `ix_usage_events_program_id_user_ts` | PII (identifier) | GROUP BY key |
| ts | datetime (tz-aware UTC) | part of NEW `ix_usage_events_program_id_user_ts` | — | range predicate (`ts >= range_start`) |
| session_id | str | — | — | `COUNT(DISTINCT session_id)` → `sessions` |
| tokens | int | — | — | `SUM(tokens)` → `tokens` |

`program_members` and `usage_events` are merged by `user_id`/`user` in Python (D-01) — never a
SQL join, to keep the query count fixed at exactly two and avoid a Cartesian product.

## 2. Migrations

New Alembic migration `008_program_team_index.py` adds
`Index("ix_usage_events_program_id_user_ts", "program_id", "user", "ts")` on `usage_events`
(ADR-0016, D-02). Forward-only-safe with a real `downgrade()` (index drop, no data loss either
direction). Declared identically in the `UsageEvent` ORM model's `__table_args__`
(`app/models/ingestion.py`) per this repo's schema-diff gate
(`tests/test_migrations.py::TestSchemaDiffGate`) and the fixture-driven constraint test
(`tests/test_models.py::TestFixtureDrivenTableConstraints`). No backfill — an index add requires
none; Postgres builds it against existing rows at migration time (no `CONCURRENTLY` clause is
in use anywhere else in this repo's migrations, so this migration matches that existing
precedent rather than introducing a new one).

## 3. Ownership & tenancy

No per-user or per-tenant scoping on the team-table route — `program_visibility()` (AUTH-03) is
called once as an open-aggregate veto gate (passes for any authenticated session, never filters
by `current_user.programs`), matching PGD-01..04. The popup's sibling route
(`GET /program-detail/{program_id}/team/{member_id}/usage`, D-04) is scoped by
`member_in_program_visibility(current_user, program_id, member_id)` — self or cio, enforced
server-side before `fetch_personal_usage()` is ever invoked (403 short-circuits with no data
call, satisfying AC-12's mutual-exclusivity requirement by construction, not by a post-hoc
response-body check).

## 4. Data classification & retention

`program_members.name` and `usage_events.user` are PII (identifiers); `program_members` rows
are classified Confidential per REQUIREMENTS.md § NFR Security. No new classification is
introduced — both fields are already covered by their owning tables' existing classification
(BED-01, ING-02). Retention of both tables is owned by their original ingest stories, unchanged
here. No new PII field ships on the wire beyond `member_name` (already an existing
`program_members.name` passthrough for every other PGD sibling's roster-adjacent reads).

## 5. Consistency & concurrency

Two read-only SELECTs per team-table request, no write, no transaction boundary to declare, no
concurrent-write conflict possible. The popup's sibling route is also read-only (delegates to
SHP-02's own `fetch_personal_usage()`, unchanged). `program_members` itself is rebuilt
synchronously by BED-03 on every ING-02 ingest (verified, research Exploration Log) — no async
rebuild coordination needed for this story (decision log (e)); a request during an in-flight
rebuild reads whatever the current committed row is, same read-committed behavior every other
PGD sibling already accepts.

## 6. Caching

No cache. Every request re-runs both aggregate queries — matching PGD-01..04's precedent (no
cache layer exists on this router). `no TTL — no cache` is the deliberate answer, not an
oversight.

## 7. Ephemeral / session state

N/A on the backend (stateless request/response). On the frontend, the selected range chip
(`7d`/`30d`/`90d`) for the team table is client-owned UI state per DESIGN.md — no server or URL
persistence. The popup's own open/closed state (once its design lands, D-05) will also be
client-only component state — not planned in detail here since the component itself is
design-gated.

## 8. Query-path & access-path performance

Exactly two SELECTs per team-table request (PGD-05-FR-1): (1) `program_members` filtered by
`program_id` (existing `ix_program_members_program_id`), (2) `usage_events` filtered by
`program_id` + `ts >= range_start`, grouped by `user` (NEW `ix_usage_events_program_id_user_ts`,
D-02/ADR-0016). No N+1, no join-produced Cartesian product — merge happens in Python
(`.claude/rules/performance-baseline.md`). No pagination — the mockup places no cap on row count
(DESIGN.md § Not specified by the mockup) and per-program member cardinality is bounded by the
program's real roster size, not unbounded user-generated data. NFR-002 (≤2s) is verified by
`tests/perf/test_program_team_perf.py` (query-count spy asserting exactly 2 SELECTs + wall-clock
≤2s at seeded volume, mirroring PGD-02/03/04 precedent).

## 9. Contract (API / interface)

Registered cross-story contract: `program-team-api`
(`docs/requirements/api.md#program-team-api`, `produced_by: PGD-05`,
`consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01, SHP-07]`). The concrete shape is authored there
(this story fills in the sketch — PLAN.md § 5 T-09). This section is a bookmark, not a copy:

Contract: `program-team-api` → `docs/requirements/api.md#program-team-api`

Route summary (full detail in the contract above and in `README.md`'s API table):
`GET /api/overview/program-detail/{program_id}/team?range=7d|30d|90d` (default `30d`) →
`200 ProgramTeamResponse { items: [{member_name: str, role: str, sessions: int, tokens: int,
avg_tokens_per_session: int}] }`, ordered descending by `tokens`; `400 invalid_range`; `401`
unauthenticated. No `404` — zero active members returns `200 {items: []}` (decision log (b)).

Popup data path (D-03/D-04, not a registered cross-story contract — reuses `personal-usage-api`
verbatim, `docs/requirements/api.md#personal-usage-api`, `authz_note`): new sibling route
`GET /api/overview/program-detail/{program_id}/team/{member_id}/usage?range=7d|30d|90d` →
`200 PersonalUsageResponse` (SHP-02 shape, unmodified) gated by `member_in_program_visibility`;
`403` (no data body) on denial, logged `member_view_denied`; `400 invalid_range`; `401`
unauthenticated.

## 10. Async & messaging

N/A — purely synchronous request/response; no event, job, or queue involved.
