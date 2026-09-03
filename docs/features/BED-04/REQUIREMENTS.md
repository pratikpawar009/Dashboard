# Feature: BED-04 — Ingestion freshness accessor

## Problem

Every dashboard view renders numbers derived from ingested SDLC activity, but nothing tells the viewer how current those numbers are. Ingestion runs out-of-process and is manually triggered — no scheduler exists (`FR-ING-11` is Could-Have) — so the gap between the last successful ingest and now is unbounded and invisible. A viewer cannot tell a fresh snapshot from one frozen by an ingestion outage, and today each of the five dashboard-composition stories would have to read `system_metadata` itself to find out.

## Outcome

One in-process accessor returns the `system_metadata` singleton's `last_successful_run_at` as a timezone-aware datetime, serves it from a 300-second cache, and raises an error stating "ingestion job may not have run yet" when the row is absent. OVW-01, ARC-01, DEV-01, PMD-01 and EMD-01 consume it through the `freshness-api` contract instead of each querying the table, so worst-case apparent staleness is bounded at 5 minutes and stated in one place.

## Constraints

- **Schema is fixed upstream.** BED-01's `db-schema` contract pins `system_metadata(key String PK, last_successful_run_at DateTime(timezone=True) NOT NULL)`; `app.models.ingestion.SystemMetadata` is the ORM source of truth. This story adds no migration and no model change.
- **Contract shape is fixed.** `docs/requirements/api.md#freshness-api` pins `fields: { last_successful_run_at: "datetime" }` — a raw datetime, **not** a pre-formatted display string. Five stories consume it; renaming the field or changing its type is a breaking change.
- **Error string is verbatim.** "ingestion job may not have run yet" (source PRD `FR-BE-05`, `docs/prd/ai-sdlc-adoption-dashboards.md` line 236). Paraphrase breaks consumers that log or match it.
- **No writer exists.** ING-01 (merged, PR #179) added ingest-token minting and bearer auth only; nothing yet writes `last_successful_run_at`. Cache invalidation is therefore TTL-only by necessity — the writer is out-of-process and cannot invalidate an in-process cache, so the TTL length *is* the worst-case apparent staleness.
- **TTL is 300s**, matching `services/api/app/core/persona_resolver.py` `_CACHE_TTL_SECONDS = 300.0`, so the API has one cache duration to reason about (story Decision log, 2026-09-03).
- **Module path is `services/api/app/services/freshness.py`.** The story's `backend/app/services/freshness.py` is stale reference-implementation drift; research measured it as systemic (90 PRD lines, 25 story files, only BED-02 corrected) and no gate catches it.
- **The mockups bind no freshness value.** All six decoded mockups were searched: no `lastUpdated` / `asOf` / freshness binding exists in any of them, so there is no pre-formatted display form to satisfy and nothing for this story to design against. The raw datetime the contract pins is the correct output; whichever story adds the display element owns its formatting.

## Solution sketch

A single read-only service accessor over the `system_metadata` singleton, following the caching shape already proven by `PersonaResolver`: a monotonic-clock TTL, a warm fast path, and one indexed primary-key read on a miss. The row-absent case is a first-class outcome, not an incidental failure — it means "ingestion has never run", is logged at warning level so operators can tell an unseeded database from an outage, and surfaces to the caller with the fixed message. No HTTP route is added; the accessor is a service consumed by the dashboard-composition stories.

## Scope

- **In**: the `freshness.py` accessor module; its 300s monotonic-clock TTL cache; the row-absent error with the verbatim message as a module constant; the warning-level log on that path; unit coverage for all four ACs and the behavioural test cases below.
- **Out**: any HTTP route or response envelope (owned by the consuming stories); any UI rendering or display formatting of the timestamp; the ingestion writer that updates `last_successful_run_at` (ING-02+); a real-writer integration test (deferred to ING-02 per research recommendation 4); RBAC gating (none applies — see NFRs); the systemic `backend/` path drift across the other 24 stories (carry-forward `CF-BED-04-01`); adding a freshness element to the six mockups (carry-forward `CF-BED-04-02`).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/BED-04.md` for canonical wording.
New impl constraints introduced below (when any):

**BED-04-FR-1** — Accessor contract: fixed message constant, warning log, error class  *(extends AC #2 with: the message must be a module constant, the warning log is mandatory on that path, and the raised error's status is pinned)*

The row-absent path carries three constraints the AC does not state:

- The message is a module-level constant (`_NOT_RUN_MESSAGE = "ingestion job may not have run yet"`), used by both the raise and the log event, so the string cannot drift between them or across refactors. Research risk #2: five downstream consumers may log or match it.
- A `logger.warning()` event is emitted on every row-absent call, via the existing `app/core/logging.py` `JSONFormatter` `extra={...}` seam, so operators can distinguish a never-seeded database from an ingestion outage (story NFR, Observability).
- The error raises as `HTTPException(500)`, matching the generic unhandled-exception handler in `app/core/errors.py`. `503` is arguably more semantically correct for "dependency has not produced data yet"; `500` is chosen for consistency with the existing handler and recorded here so a consumer needing `503` escalates rather than silently diverging (research risk #5).

## Non-functional requirements

- Performance: warm cached read completes in **< 10 ms p95** — in-process dict lookup on a monotonic clock, no I/O on the hit path (story NFR; assumption, no source budget exists). A cache miss is one primary-key `select(...).where(key == 'ingestion').limit(1)`, so cost is bounded at one indexed row read per 300s regardless of call volume.
- Performance: Per `.claude/rules/performance-baseline.md`: cache TTL and its invalidating event are documented — 300s, TTL-expiry only, because the writer is out-of-process (see Constraints). No retry, no unbounded wait; the single read is bounded by an explicit 3.0s `asyncio.wait_for` timeout, matching `app.core.persona_resolver`'s Tier-3 bound (D-04).
- Security: Per `.claude/rules/security-baseline.md`: applies to the new accessor. Read-only, and deliberately **not** persona-gated — the freshness timestamp is shown on every dashboard view regardless of persona (source PRD glossary, "Freshness timestamp"), so no RBAC check applies. The accessor reads two non-PII columns (`key`, `last_successful_run_at`) and logs neither a user identifier nor request content.
- Accessibility: N/A — backend service accessor, no UI surface in this story.
- Observability: `logger.warning()` on the row-absent path per **BED-04-FR-1**, and one on the query-timeout path per **D-04** — both carry the same PII-free `extra={"reason": ...}` shape, and the two are mutually exclusive, so a single call emits at most one record. No log on the cache-hit path — research recommendation 5 suggested an optional debug event; declined to keep the warm path allocation-free against the < 10 ms budget.

## Visual spec

Not applicable — `design = n/a`. `BED` has no epic in `docs/design/schema.json` `designSystem.pages.features`, which is the only condition under which `CLAUDE.md` permits `design: n/a`. No `DESIGN.md` is produced. See Constraints for the searched-and-absent freshness binding.

## Rollout plan

- **Strategy**: bang-bang — a new service module with no route and no caller in production; nothing live to stage or migrate.
- **Feature flag**: none — not a runtime-toggleable behaviour; the only callers until OVW-01 ship are its own tests.
- **Backout plan**: delete `services/api/app/services/freshness.py` and its test module. Nothing imports the accessor until a dashboard-composition story wires it, so revert needs no coordination and no redeploy of any other component.
- **Success signal**: all three behavioural test cases in `docs/test-cases/BED-04.json` pass, including the p95 < 10 ms warm-read budget — gates the `/arh-plan-requirements` run of the five consuming stories, which cannot bind `freshness-api` until its shape is proven.

## Documentation requirements

- **README updates**: `services/api/README.md` — document the `freshness-api` contract as consumers see it: `get_last_successful_run()`'s return type (timezone-aware datetime, not a display string), the 300s TTL and that TTL expiry is its *only* invalidating event, and the row-absent error message + status.
- **Runbook**: none — no operational runbook for an internal accessor with no route. The warning log is the operator-facing surface and is documented with the README entry.
- **API reference**: none — this story introduces no HTTP endpoint.
- **Inline code comments**: `freshness.py` module docstring must record (a) that no writer exists yet, so AC-4 is fixture-verified until ING-02 (research risk #1), and (b) the `500`-over-`503` choice from **BED-04-FR-1**.
- **Examples / how-to**: none.

## Open questions

<!-- None open. Research (docs/research/BED-04.md) carried 0 unresolved clarifications  -->
<!-- into this phase and its verdict is GO with no conditions, so no                    -->
<!-- § Addressing Research Conditions section is emitted. Decisions are logged in       -->
<!-- docs/stories/BED-04.md § Decision log.                                             -->
<!--                                                                                     -->
<!-- Two findings surfaced during this phase are recorded as carry-forward entries in    -->
<!-- state.json (CF-BED-04-01 systemic `backend/` path drift, CF-BED-04-02 no freshness   -->
<!-- binding in any mockup) rather than as open questions: neither blocks this story's    -->
<!-- implementation, and both are owned outside its scope.                               -->
<!--                                                                                     -->
<!-- Kept as a comment deliberately: the `phase-preconditions` clarification gate         -->
<!-- treats ANY non-blank, non-comment line in this section as an unresolved open         -->
<!-- question and aborts the next phase. Prose saying "None" trips it.                    -->

## Approvals

| Role | Approver | Date | Verdict |
|---|---|---|---|
| Product Owner / BA | Pratik Pawar (pratik.pawar@apexon.com) | 2026-09-03 | APPROVE |
| Designer | — | 2026-09-03 | N/A — `design = n/a`, no `BED` epic in `docs/design/schema.json` |

Product Gate passed at `/arh-plan-requirements` Phase 4. Checklist evidence at approval time: research verdict GO with no conditions, so § Addressing Research Conditions is correctly absent; 0 unresolved `[NEEDS CLARIFICATION]` markers carried from `docs/research/BED-04.md`; section set matches the pinned `prd-template` list (F-051 silent), `## Screen inventory` omitted as backend-only; one delta FR emitted, three ACs left FR-free under the delta-only rule; test-case coverage audit `uncovered == []` across 3 cases, every `requirement_id` resolving to a real AC/FR/NFR id.

**Test-case count is user-capped at 3** ("just create 2-3 test cases not more than that"). Consequence, accepted at approval: no dedicated `type: contract` case pins the `freshness-api` field shape that five stories bind, and no dedicated `type: security` case asserts the deliberate absence of RBAC gating. Both obligations are unbudgeted NFRs, so the coverage minimum does not require them, but the first would normally be written given five downstream consumers.
