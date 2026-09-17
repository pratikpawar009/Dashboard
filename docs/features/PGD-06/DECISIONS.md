# PGD-06 — Decisions

Decision log for the daily session-time series API + Next.js proxy. Header slugs (`blast:`/`rev:`)
are the greppable half of the record; `plan-validation`'s Decision-promotion dimension reads them.

### D-01: Org-wide view is a cross-member SUM, not a `member_id IS NULL` read · blast:feature · rev:mechanical · adr:—

**Context**: REQUIREMENTS.md corrects the story's original AC-1 premise (C-1): `session_series`
has a nullable `member_id` column in the schema, but `_build_session_series`
(`app/services/rollup_rebuild.py:305-333`) never actually writes a null-`member_id` row — every
row it produces carries a real `member_id=user`. Implementing AC-1 literally (`WHERE member_id IS
NULL`) would silently return an all-zero series for every program, forever, since that predicate
matches zero rows in production data.

**Decision**: `fetch_program_session_series()` computes the unfiltered/org-wide view by summing
`session_time_seconds` across every member row for the program, per day (`GROUP BY date`, no
`member_id` filter at all) — never a `member_id IS NULL` predicate. `PGD-06-TC-01` pins this
structurally: two distinct members' same-day rows must sum, proving the aggregate is a real
cross-member SUM and not a filter that happens to match nothing.

### D-02: No new index; org-wide query accepted at current volume · blast:feature · rev:mechanical · adr:—

**Context**: Research Risk #4 assumed a `(program_id, member_id, date)` composite index was
required. REQUIREMENTS.md's Addressing Research Conditions corrects this: the only index
touching these columns is the 4-column unique constraint
`uq_session_series_org_id_program_id_member_id_date` on `(org_id, program_id, member_id, date)`
(`app/models/rollup.py`). An org-wide query (no `member_id` filter, summed across members) does
not benefit from the constraint's leading `member_id` position the way a single-member lookup
would — it scans by `(org_id, program_id, date)`, a strict prefix-minus-one of the existing
constraint, not a fully-covered index prefix. REQUIREMENTS.md explicitly says no new migration
ships in this story, and volume is bounded (`member_id` cardinality × 90 days).

**Decision**: Ship the org-wide query as `SELECT date, SUM(session_time_seconds) FROM
session_series WHERE program_id = :pid AND date >= :range_start GROUP BY date` — no new index, no
migration. This is accepted, not silently ignored: if a future story's data volume makes this scan
pattern a measured problem (per `.claude/rules/performance-baseline.md` — profile, then change),
the fix is a dedicated migration story, not a retrofit here. `PGD-06-TC-17`'s perf budget (≤2s at
≥5,000 rows / ≥50 members over 90 days) is the concrete check this decision is accountable to.

### D-03: `org_id` is not read or filtered by this endpoint · blast:feature · rev:mechanical · adr:—

**Context**: `session_series` carries an `org_id` column, part of the 4-column unique constraint.
`_ORG_ID = "org-1"` (`app/services/rollup_rebuild.py:118`) is a hardcoded single-org singleton —
every writer stamps that one literal, and the system has no multi-tenancy today. Neither the story
nor REQUIREMENTS.md names an org-scoping FR/AC, and the two gates this story specifies
(`program_visibility`, `member_in_program_visibility`) are program-scoped, not org-scoped. The
test-case coverage audit flagged this explicitly and the orchestrator resolved it pre-Product-Gate
(2026-09-17): no cross-org isolation requirement exists for this story.

**Decision**: `fetch_program_session_series()` filters only on `program_id` (and optionally
`member_id`) — it never reads or filters on `org_id`. This matches every other PGD sibling
service (`fetch_program_token_trend`, `fetch_program_team`, `fetch_program_commands`), none of
which filter on `org_id` either, despite `program_token_series`/`program_members` carrying no
`org_id` column at all — `session_series` is the only session-scoped table with the column, and
this decision keeps PGD-06 consistent with its siblings rather than introducing an org predicate
none of them has. Should real multi-org support ever land, org scoping becomes a system-wide
concern for a dedicated story (`blast:system` at that point), not a retrofit onto this endpoint.

### D-04: Response shape and gating mirror the token-trend / team-popup precedents exactly · blast:feature · rev:mechanical · adr:—

**Context**: REQUIREMENTS.md settles every shape question against a named sibling: raw-int fields
(matching `/token-trend`, not `/releases`), no-404-on-unknown-`program_id` (matching
`/token-trend`/`/commands`/`/team`, not `/releases`), zero-padding to the fixed range length, and
gate-before-query ordering via `member_in_program_visibility` (matching `/team/{member_id}/usage`,
PGD-05 D-04). None of these are new choices — the decision worth recording is committing to
*inherit* rather than re-derive them, since a competent implementer could otherwise reach for the
releases route's 404/pre-formatted-string precedent by mistake (same router, different sibling).

**Decision**: `GET /api/overview/program-detail/{program_id}/session-time-series` is registered as
an eighth sibling on the existing `overview` router. `program_visibility(current_user, program_id)`
runs first (open-aggregate veto, no logging on pass); when `member_id` is present,
`member_in_program_visibility(current_user, program_id, member_id)` runs next, before any
`session_series` query (mirroring PGD-05's `/team/{member_id}/usage` call order exactly — see
`app/core/rbac.py::member_in_program_visibility`'s own `program_visibility`-first-always
contract). No `program_summary` existence lookup; unknown `program_id` returns `200` with an
all-zero zero-padded series. `points[].session_time_seconds`, `period_total_seconds`,
`avg_seconds_per_day` are raw ints; `avg_seconds_per_day` divides by the range's fixed day count
(7/30/90), never the count of days with data — reusing `range_to_start`/`_range_with_default`
unedited, no bespoke range parsing.

### D-05: Frontend ships proxy-only; no chart or filter component this story · blast:feature · rev:mechanical · adr:—

**Context**: REQUIREMENTS.md § Scope documents that no mockup shows a session-time chart or member
filter anywhere in the six dashboards (`dashboards/Program Detail.html` has exactly six sections,
none of them this chart; the Engineering Manager Dashboard mockup adds only a MEMBER COMMAND
POPUP). The story's own Test-mapping names `SessionTimeChart.tsx`/`MemberFilter.tsx` as "unchanged
components", but neither exists under `apps/web/src` — the same "story claims a component that
does not exist" finding PGD-04 documented. `CLAUDE.md` § Design system forbids inventing a screen
the mockups do not show.

**Decision**: This story ships the FastAPI route + service + schema, and a Next.js proxy Route
Handler at `apps/web/src/app/api/proxy/program-detail/[program_id]/session-time-series/route.ts`
(ADR-0008 pattern, mirroring the existing `token-trend`/`commands`/`team` proxies exactly —
`callWithAuth` retry-once, range passthrough with absent-means-`undefined`, status mapping). No
chart component, no filter component, no CSS module, no component test. Rendering is deferred to
a follow-on story scoped against a design that actually shows this chart.
