# Feature: AUTH-04 — GET /api/programs persona-scoped list

## Problem

PGD-01's and EMD-01's "Switch program" selectors need a program list scoped to what the signed-in caller may see. No such endpoint exists today; without one, each consumer would reimplement scoping against `session.groups` independently, risking a program leak to a non-member on any consumer that gets the filter wrong.

## Outcome

`GET /api/programs` returns exactly the programs the caller may see — every row for `cio`, only the rows matching `session.programs` for every other persona — in the shape the switcher list actually renders. PGD-01 and EMD-01 consume the response with zero client-side reshaping.

## Constraints

- FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2.9 — existing stack, no new dependency.
- Consumes AUTH-01 `session` (`CurrentUser: user_id, email, role, groups, programs`), AUTH-02 `persona-resolver` (`resolve(role) -> persona`, raises `PersonaNotFoundError | PersonaResolutionError`), AUTH-03 `rbac-checks.program_visibility` (open-aggregate veto gate), BED-01 `db-schema.program_summary` — all four complete and merged to `main`.
- Response shape is fixed by **ADR-0005** (`docs/adr/0005-programs-api-switcher-shape.md`): `{program_id, label, href, dotStyle}`. Story `docs/stories/AUTH-04.md` AC-5 names an older field set (`program_id, name, icon, type, description`); ADR-0005 supersedes it. The story file is not edited — it is `Status: Validated`, and re-opening it would force re-validation — so this PRD carries the corrected field set, with ADR-0005 as authority, and the story edit is carried forward.
- No pagination — org sized at ~9 programs (NFR-004 seed fixture); this story has no `api-conventions` (BED-02) dependency in the RTM.
- Stateless: AUTH-01's `session` contract has no server-side session store, so this endpoint receives no active-program input.

## Solution sketch

A single `GET /api/programs` route resolves `CurrentUser` via the shared auth dependency, resolves persona via AUTH-02's resolver, and either returns every `program_summary` row (`cio`) or filters to `program_id IN current_user.programs` (every other persona). Each row maps to `{program_id, label, href, dotStyle}` — `label` from `program_summary.name`, `href`/`dotStyle` derived server-side — and the call logs one `programs_list_returned` event.

## Addressing Research Conditions

Research verdict GO-WITH-CONDITIONS, 84/100, CERTIFIED 2026-08-31. Six conditions (0–5) from `docs/research/AUTH-04.md` § Conditions for proceeding to `/arh-plan-requirements`:

- **C-0 (response shape, was BLOCKING)** — DONE 2026-08-31: settled as Option C (split) by **ADR-0005**. `GET /api/programs` returns `{program_id, label, href, dotStyle}`; `type`/`description` leave this endpoint (already carried by `program-detail-api` § header and `persona-shell` § `program_context`); `current`/`rowStyle` are client-derived. Not re-opened here.
- **C-1 (logging event payload)** — `programs_list_returned` payload is exactly `{user_id, persona, returned_count, timestamp}` — no email, groups, or request path (security-baseline PII audit). See AUTH-04-FR-1. Mitigation: a unit test (AUTH-02 TC-15 pattern) asserts the payload key set equals the allowlist exactly.
- **C-2 (`program_visibility` semantics)** — documented as a veto gate that passes for any authenticated session; actual scoping is the `WHERE program_id IN current_user.programs` clause, never `program_visibility`'s result. See AUTH-04-FR-2 and the endpoint-docstring requirement in Documentation requirements.
- **C-3 (persona-resolution error handling)** — catch `PersonaNotFoundError` and `PersonaResolutionError`, log at WARN, return `HTTPException(403, "Access denied")` — fail-closed, consistent with AUTH-03. See AUTH-04-FR-3. Mitigation: a unit test mocks a persona-resolver timeout and asserts 403.
- **C-4 (performance baseline)** — seed ~100 programs (2x org size), a non-cio persona scoped to 50, measure end-to-end latency (persona resolution + DB query + serialization), assert p95 < 300ms, capture the baseline. See Non-functional requirements § Performance.
- **C-5 (defensive handling of missing programs)** — a `program_id` in `session.programs` absent from `program_summary` is filtered out by the WHERE clause, never raised; log a WARN when `returned_count < len(current_user.programs)`. See AUTH-04-FR-4.

## Scope

**In:**
- `GET /api/programs` route: cio-sees-all / non-cio `session.programs` scoping.
- Response model `{program_id, label, href, dotStyle}` per ADR-0005.
- `programs_list_returned` logging event (allowlist per AUTH-04-FR-1).
- Fail-closed persona-resolution error handling (AUTH-04-FR-3).
- Defensive WHERE-clause filtering + discrepancy WARN log (AUTH-04-FR-4).

**Out:**
- Pagination — deferred; org sized at ~9 programs (NFR-004), no `api-conventions`/BED-02 dependency declared for this story. No downstream story id assigned yet; revisit if the org outgrows this scale (research Risk #7).
- `type`/`description` fields — owned by `program-detail-api` (PGD-01 header) and `persona-shell` (SHP-01 `program_context`), not this endpoint (ADR-0005).
- `current`/`rowStyle` — client-derived by the switcher consumer (PGD-01, EMD-01) by comparing `href` to the active route; this endpoint receives no active-program input.
- Per-program `403` — AC-6 confirms `program_visibility` never issues one for this list; scoping is inclusion-based, not a per-program authorization gate.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/AUTH-04.md` for canonical wording. New impl constraints introduced below:

**AUTH-04-FR-1** — Response field set and logging payload allowlist *(extends AC-5 with: ADR-0005 supersedes AC-5's field set; extends the Observability NFR with an exact payload)*

Each program entry is exactly `{program_id, label, href, dotStyle}` per ADR-0005 — `label` = `program_summary.name`; `href` derived server-side from `program_id` (routes to `program-detail-api`'s `GET /api/overview/program-detail/{program_id}`); `dotStyle` = pre-formatted CSS for the indicator dot. `type`/`description` are never included, superseding AC-5. The `programs_list_returned` log event payload is exactly `{user_id, persona, returned_count, timestamp}` — no email, groups, or request path.

**AUTH-04-FR-2** — `program_visibility` is a veto gate, not a roster source *(extends AC-6 with: explicit semantics)*

`program_visibility(current_user, program_id)` passes for any authenticated session (open-aggregate, A-004) and is called, at most, once as a session-validity check — never per-program. Actual scoping is entirely the `WHERE program_id IN current_user.programs` clause (non-cio) or no filter (cio). The endpoint docstring states this explicitly so downstream consumers never read a `200` as confirmation of program membership.

**AUTH-04-FR-3** — Persona-resolution error handling *(extends AC-1 with: fail-closed error path)*

Every call to `persona_resolver.resolve(current_user.role)` wraps `PersonaNotFoundError` and `PersonaResolutionError` in a try/except; either raises `HTTPException(403, "Access denied")` and logs at `logging.WARNING`, consistent with AUTH-03's fail-closed posture. Neither exception ever propagates as a `500`.

**AUTH-04-FR-4** — Defensive filtering of missing programs *(extends AC-2/AC-4 with: no-raise on data discrepancy)*

A `program_id` present in `current_user.programs` but absent from `program_summary` is silently excluded by the WHERE clause — never raised. When `returned_count < len(current_user.programs)`, log a WARN event (distinct from `programs_list_returned`) signalling a data discrepancy for ops investigation.

## Non-functional requirements

- Performance: p95 < 300ms end-to-end (persona resolution + DB query + serialization) for the full unpaginated list. Baseline measured against a ~9-program seed fixture (NFR-004) and validated under a seeded ~100-program dataset with a non-cio persona scoped to 50 (condition C-4) — capture the measured baseline for future optimization stories.
- Security: Per `.claude/rules/security-baseline.md`: bearer-JWT validated per request via AUTH-01's `session` contract; scoping derived server-side from `current_user.programs` only, never a client-supplied filter. `programs_list_returned` payload is `{user_id, persona, returned_count, timestamp}` — no email, groups, or request path (condition C-1).
- Accessibility: N/A — backend endpoint, no UI surface in this story.
- Observability: `programs_list_returned` event on every call (AUTH-04-FR-1 allowlist); a separate WARN event when `returned_count < len(current_user.programs)` (AUTH-04-FR-4, condition C-5).

## Visual spec

Not applicable — `integrations.design = none`. Backend / API / data feature.

## Rollout plan

- **Strategy**: bang-bang — additive new endpoint; no existing consumers to break (PGD-01/EMD-01 not yet implemented).
- **Feature flag**: none.
- **Backout plan**: revert the PR / remove the router include in `app.main`; no schema or data migration.
- **Success signal**: PGD-01's and EMD-01's switcher selectors render from this endpoint's response with zero client-side reshaping, and the C-4 performance baseline test reports p95 < 300ms.

## Documentation requirements

- **README updates**: `services/api/README.md` — add `GET /api/programs` to the API table: endpoint, scoping rule, response shape.
- **Runbook**: none.
- **API reference**: FastAPI's generated `/docs` (OpenAPI) — response model documented via Pydantic field descriptions.
- **Inline code comments**: `app/api/programs.py` module/route docstring covering `program_visibility`'s veto-gate semantics (AUTH-04-FR-2), the fail-closed persona-resolution error path (AUTH-04-FR-3), and the missing-program discrepancy WARN log (AUTH-04-FR-4).
- **Examples / how-to**: none — `docs/requirements/api.md` § `programs-api` already documents the contract for PGD-01/EMD-01.

## Open questions

<!-- None open. The sole research clarification (C-1, response shape) was resolved   -->
<!-- 2026-08-31 by ADR-0005 and is recorded in § Addressing Research Conditions      -->
<!-- (C-0) and § Approvals. No new ambiguity surfaced during drafting.               -->
<!-- Decisions logged in docs/stories/AUTH-04.md § Decision log.                     -->
<!-- needs_clarification_count: 0.                                                   -->
<!--                                                                                 -->
<!-- Kept as a comment deliberately, matching AUTH-02: the `phase-preconditions`     -->
<!-- clarification gate treats ANY non-blank, non-comment line in this section as an -->
<!-- unresolved open question and aborts the next phase. Prose saying "None" trips   -->
<!-- it. -->

## Approvals

- **2026-08-31** — Pratik Pawar (PO): **APPROVE**
  - Problem, Outcome, Functional requirements reviewed
  - UI specs reviewed in `DESIGN.md`: N/A — `design = n/a`, backend-only feature (AUTH epic has no entry in `docs/design/schema.json` → `designSystem.pages.features`)
  - Edge Cases, Open Questions (0 open), and test-case completeness/automation feasibility reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO-WITH-CONDITIONS, 84/100 (all 6 conditions C-0..C-5 addressed in § Addressing Research Conditions)
  - C-0 settled before the gate: response shape is `{program_id, label, href, dotStyle}` — Option C (split), recorded as **ADR-0005** and reflected in `docs/requirements/api.md` § `programs-api`. `current`/`rowStyle` are client-derived: a deliberate, narrow exception to the "values arrive pre-formatted" decision, scoped to route-dependent state only.
  - **Carry-forward**: `docs/stories/AUTH-04.md` AC-5 still names the superseded field set. The story is `Status: Validated` and was deliberately not edited (re-opening forces re-validation); this PRD plus ADR-0005 are authoritative on response shape.
  - Test cases: 18 total, 18 automatable, `coverage_audit.uncovered=[]`
  - Pre-push secret scan: `AUTH-04-TC-04` `test_data.bearer_token` flagged by the key-name rule; reviewed at gate as a false positive (a deliberately invalid JWT literal, not a credential) and retained — dropping it would cost AC-3 half its coverage.
  - Tracker subtask: pratikpawar009/Dashboard#132
