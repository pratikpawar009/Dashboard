# Story: BED-02 — Shared API conventions: range validation, pagination, derived-value computation, formatting

**Epic**: BED
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-27
**Tracker**: pratikpawar009/Dashboard#12 (https://github.com/pratikpawar009/Dashboard/issues/12)
**Tracker Research**: pratikpawar009/Dashboard#63 (https://github.com/pratikpawar009/Dashboard/issues/63)
**Tracker Plan Requirements**: pratikpawar009/Dashboard#64 (https://github.com/pratikpawar009/Dashboard/issues/64)
**Tracker Plan Implementation**: pratikpawar009/Dashboard#82 (https://github.com/pratikpawar009/Dashboard/issues/82)

## User story

As a backend developer building any dashboard endpoint, I want a shared set of API
conventions (range validation, pagination, derived-value computation, numeric/time
formatting) so that every time-series/list endpoint behaves consistently and downstream
routers don't each reinvent these rules.

## Acceptance criteria

1. Given a time-series or list endpoint receiving `range=7d`, `range=30d`, or `range=90d`,
   when the request is processed, then the endpoint accepts the value and scopes its query
   accordingly (FR-BE-02).
2. Given a time-series or list endpoint receiving a `range` value outside `{7d, 30d, 90d}`,
   when the request is processed, then the endpoint returns `HTTP 400` via an explicit check
   (never FastAPI's default `422` type-coercion error) (FR-BE-02, PRD §5.3).
3. Given an endpoint supporting offset-based pagination, when `limit` is omitted or exceeds
   the per-endpoint max, then the endpoint clamps to a max of `50` (FR-BE-03).
4. Given an endpoint supporting page-based pagination, when `page_size` is omitted or exceeds
   the per-endpoint max, then the endpoint clamps to a max of `100` (FR-BE-03).
5. Given a response field is a derived value (adoption %, delta, average, "X/Y passing"),
   when the response is built, then the value is computed server-side in
   `services/api/app/services/*.py` — never left for the frontend to compute (FR-BE-04).
6. Given a numeric or duration value is included in a response, when the shared formatting
   utility is applied, then output uses consistent M/K numeric formatting and h/m time
   formatting, applied at exactly one layer (backend-only or frontend-only, per the project's
   chosen layer — not mixed) (FR-BE-08).
7. Given the shared range-validation dependency is reused by two or more routers, when either
   router is exercised with the same invalid `range` value, then both return identical
   `400` status and error-body shape (consistency across consumers of this contract).

## Non-functional requirements

- Performance: range/filter-change refresh (endpoints built on this contract) responds in
  ≤ 2s (NFR-002, per PRD).
- Security: N/A — this story defines no new auth surface; consuming endpoints apply their own
  RBAC (AUTH-03) independently of these conventions.
- Accessibility: N/A — backend-only contract, no UI surface.
- Observability: validation failures (400 on invalid `range`) are logged via the project's
  structured `structlog`/`logging` JSON output — 2026-08-26 log fields: `route`, `param`,
  `rejected_value` — assumption, PRD NFR-011 establishes the structlog convention and event
  set but does not enumerate fields for this specific rejection path.

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md`) — this story's
  pagination/derived-value helpers operate over the 17-table shape BED-01 migrates; consumed
  as a stub-buildable dependency (models don't need to be live, only the shape frozen).
- Downstream: OVW-01..04, PGD-01..06, SHP-02..06 all consume this story's `api-conventions`
  contract (`docs/requirements/api.md`) for range validation, pagination, and formatting.

## Test mapping

- E2E: NA — backend-only shared convention, exercised indirectly through consumer routers' E2E suites.
- Unit: `services/api/app/utils/format.py`, `services/api/app/dependencies/range.py` (or equivalent shared-dependency module), pagination helper module.
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 Structured-log fields for invalid-range rejection: `route`, `param`,
  `rejected_value` — assumption, NFR-011 mandates structlog JSON output and names an event
  set for RBAC/telemetry but does not specify fields for this validation-rejection path.
- 2026-08-26 Formatting layer choice left open ("pick one, backend or frontend") per FR-BE-08 —
  not resolved here; AC 6 states the constraint (single layer, no mixing) without picking a
  side, since the PRD explicitly defers that choice to implementation.
- 2026-08-27 Test-mapping/AC-5 paths corrected `backend/app/...` → `services/api/app/...` to match the
  real repo layout (README, ADR-0001). Path correction only — no acceptance-criteria semantics changed.
- 2026-08-27 Logging for the invalid-range rejection path uses the existing stdlib `logging` +
  `JSONFormatter` (`services/api/app/core/logging.py`, ADR-0002); structlog is NOT added. Resolves the
  2026-08-26 assumption above: PRD NFR-011 reads "Python `structlog`/`logging` JSON output" — either is
  compliant, and the hand-rolled formatter already ships. Condition: `JSONFormatter.format` currently
  emits only `{timestamp, level, logger, message, exc_info?}` and drops `record.__dict__` extras, so it
  must be extended to pass through `extra` before `route`/`param`/`rejected_value` can be logged.
