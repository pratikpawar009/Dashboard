# PGD-01 — Data Design

State & data management for the Program Detail page shell. Each of the ten concerns is specified
or marked `N/A — <reason>`.

## 1. Data model

No new entity, no schema change. `GET /api/overview/program-detail/{program_id}` reads one existing
row from `program_summary` (postgres table, BED-01/`db-schema`, `app/models/rollup.py:64-85`) —
owned and migrated by BED-01, not touched here.

### `program_summary` (postgres table — read-only reference, not modified by this story)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `program_id` | String | unique | — | keys this endpoint's path param |
| `name`, `icon`, `type`, `description` | String | required | — | `header` response fields verbatim |
| `tokens` | BigInteger | required | — | card 1, via `format_number()` |
| `features` | Integer | required | — | card 2, via `format_number()` |
| `releases` | Integer | required | — | card 3, via `format_number()` |
| `repos_with_harness_installed` | Integer | required | — | card 4, ratio string, NOT `format_number()` |
| `repos_total` | Integer | required | — | card 4's denominator |
| `commands_executed` | Integer | required | — | card 5, via `format_number()` |
| `lines_of_code_generated` | BigInteger | required | — | card 6, via `format_number()` |
| `user_stories_delivered` | Integer | required | — | card 7, via `format_number()` |

Every other `program_summary` column (`monthly_token_sparkline`, `active_contributors`,
`intervention_count`, `tool_rejections`, `as_of_timestamp`) belongs to PGD-02..06, not read here.

## 2. Migrations

N/A — no schema change. This story is read-only against an already-migrated table (Rollout plan
Backout: "no schema or data migration to unwind").

## 3. Ownership & tenancy

`program_summary` rows carry no owner column and no per-row ACL. Access is gated once per request
by `program_visibility(current_user, program_id)` (`rbac-checks`, AUTH-03, `app/core/rbac.py`) —
called with the REAL `program_id` (unlike `app/api/programs.py`'s sentinel-argument veto-gate
pattern, which has no per-resource id to pass). This is an open-aggregate check: it passes
unconditionally for any authenticated session and never filters by `current_user.programs`
(Clarification C-3, deliberate — program-membership scoping is explicitly out of scope for this
endpoint; the switcher *list* stays membership-scoped upstream by `programs-api`/AUTH-04). The
enforcement mechanism is therefore bearer-JWT authentication only (`get_current_user`), not
per-resource 404-not-403 ownership scoping — R-003/Q-001 (the resulting risk) stays open, owned by
`/arh-security-review`, not this story.

## 4. Data classification & retention

No PII in the fields this endpoint returns — `name`/`description`/`type`/`icon` are program
metadata (not personal data), and the 7 metrics are aggregate counts. No new retention policy is
introduced; retention of `program_summary` itself is BED-01's concern, unchanged here.

## 5. Consistency & concurrency

Single read-only `SELECT`, zero writes, no transaction boundary beyond the implicit read
transaction `AsyncSession` opens. No idempotency key needed (GET is naturally idempotent). No
concurrent-write handling needed — this story performs no writes to `program_summary` or any other
table.

## 6. Caching

None. Every request reads `program_summary` directly, no TTL, no invalidation event — consistent
with `docs/adr/0002-system-architecture.md` (no cache layer exists yet in this system).

## 7. Ephemeral / session state

- **Client (React) state**: `ProgramDetailView.tsx` owns the currently-displayed
  `ProgramDetailResult` (populated/loading/error), the current `program_id`, and the switcher's
  open/closed boolean — all component-local `useState`, lost on a full page reload, not persisted.
- **URL-as-state**: the active `program_id` is carried in the route itself
  (`/programs/{program_id}`); a switcher selection updates it via `router.replace()` (client-side,
  no hard navigation, FR-4) rather than a separate query param or client store.
- No server-held per-connection state, no distributed ephemeral store (Presence/PubSub), no server
  session/flash/CSRF token — consistent with AUTH-01's stateless session design (no server-side
  session store anywhere in this system).

## 8. Query-path & access-path performance

Exactly one bounded query: `SELECT ... FROM program_summary WHERE program_id = :id` — a point
lookup against a column already carrying a `unique=True` constraint (implying a unique index),
returning 0 or 1 rows via `scalar_one_or_none()`. No pagination needed (single-row read, not a
list endpoint). No N+1: the 7 card values and the header fields all come off the same row, one
query total (PGD-01-FR-1, `.claude/rules/performance-baseline.md`). The switcher's
`GET /api/programs` call is a separate, already-scoped, already-shipped endpoint (AUTH-04) — this
story adds no new query there.

## 9. Contract (API / interface)

Contract: `program-detail-api` → `docs/requirements/api.md#program-detail-api` (concrete shape
filled by this plan; promoted to `docs/adr/0007-program-detail-response-shape.md` per DECISIONS.md
D-06 — `blast:system`, a sealed contract consumed by 4 not-yet-built sibling features).

Consumed (unchanged by this story): `programs-api` → `docs/requirements/api.md#programs-api`
(AUTH-04) — this story's only edit to that contract's implementation is the `href` field-VALUE fix
(DECISIONS.md D-04), not a shape change; the contract's own registered `shape` block already
described `href` correctly.

## 10. Async & messaging

N/A — purely synchronous request/response; no queue, topic, or background job is introduced.
