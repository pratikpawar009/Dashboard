# BED-02 — Data Design

State & data management for the shared API-conventions layer. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

No new tables/columns. BED-02 reads BED-01's existing rollup/governance tables **read-only**, via already-fetched ORM rows passed into `services/*.py` functions (D-02) — it does not construct queries itself. Full field/constraint shape lives in `docs/features/BED-01/DATA-DESIGN.md`; only the fields BED-02's compute functions actually read are named below.

| Source table (BED-01) | Fields read | Consuming function |
|---|---|---|
| `org_summary_rollup` | `programs_using_ai_count`, `programs_total` | `compute_adoption_percent` (`app/services/rollup_compute.py`) |
| *(caller-supplied totals, any rollup table)* | period totals (e.g. `token_series.value`, `mau_series.*`) | `compute_period_delta`, `compute_average` (`app/services/rollup_compute.py`) — generic over any two numeric totals/counts, not bound to one table |
| `program_guardrails` | `status` (enum `Enforced\|Warning\|NotImplemented`) | `compute_guardrail_summary` (`app/services/guardrail_compute.py`, D-05) |

## 2. Migrations

N/A — no schema change. `services/api/migrations/versions/` is untouched by this story.

## 3. Ownership & tenancy

N/A — no new owned resource. BED-02's functions are pure computation over rows the caller already fetched; org/program scoping (`org_id='org-1'` singleton convention, `program_id` filters) is enforced by whichever query fetched those rows, which is each downstream consumer router's own responsibility (OVW/PGD/SHP stories, out of this story's scope per PRD § Scope). No `_load_owned`-style check is added here because nothing here accepts a caller-supplied resource id.

## 4. Data classification & retention

N/A — no PII/sensitive field is read or returned. The one new logging surface (`route`, `param`, `rejected_value` on invalid-`range` rejection) is opaque-identifier-only per `.claude/rules/security-baseline.md` and BED-02's own NFR (`rejected_value` is the raw-but-non-PII query string, not user free text); no retention policy change.

## 5. Consistency & concurrency

N/A — every function in this story is a pure, synchronous, side-effect-free read-time computation (no writes, no transaction, no idempotency concern). `validate_range`'s only side effect is a log line on rejection, which is fire-and-forget (no consistency requirement).

## 6. Caching

N/A — no cache introduced. Every value is computed fresh per call from caller-supplied inputs; there is no TTL/invalidation surface for this story to own.

## 7. Ephemeral / session state

Query-string-as-state only: `range` (`app/dependencies/range.py`), `offset`/`limit` and `page`/`page_size` (`app/dependencies/pagination.py`) are all resolved per-request from the URL query string — no server-held session state, no cookie, no `LiveView`-style assign.

## 8. Query-path & access-path performance

- Pagination bounds (offset/limit max 50, page/page_size max 100) are enforced unconditionally by the `Depends()` helpers (D-01) — no caller can request an unbounded page, satisfying `.claude/rules/performance-baseline.md`'s "pagination on every list endpoint" for every consumer that adopts these helpers.
- `services/*.py` functions run in O(1) (rollup) or O(n) over an already-bounded row set (guardrail list, typically single-digit rows per program) — no N+1 risk since they take rows, not query specs (D-02).
- NFR-002's ≤2s range/filter-change budget is exercised end-to-end (dependency resolution + pagination clamp + one derived-value call) by BED-02-TC-18 against representative seeded row counts; see PLAN.md §7.
- Index coverage for the underlying range-scan queries themselves (e.g. `(program_id, ts)` on `usage_events`) is BED-01's concern (its research risk register, resolved there) — BED-02 does not issue those queries.

## 9. Contract (API / interface)

Registered cross-story contract — concrete shape authored once at the shared registry, this section is a bookmark only:

`Contract: api-conventions → docs/requirements/api.md#api-conventions`

## 10. Async & messaging

N/A — every function in this story is synchronous; no message/event/job is produced or consumed.
