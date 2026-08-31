# Feature: AUTH-03 — RBAC check library (org-access, program-visibility, individual-usage, member-in-program, governance)

## Problem

No shared authorization layer exists yet for the 16 stories that gate on persona (AUTH-04, OVW-01..04, PGD-01..06, SHP-02..06). Without a single library, each route would implement its own ad hoc role/persona comparisons, risking inconsistent enforcement and, worse, reliance on UI-only hiding — explicitly disallowed by the parent PRD's security NFR (NFR-005). Backend developers need five well-defined, server-side checks (org-access, program-visibility, individual-usage, member-in-program, governance) with locked signatures and deterministic pass/deny behavior, so every persona-gated route enforces authorization the same way.

## Outcome

A single in-process library, `services/api/app/core/rbac.py`, exposing five async check functions consumed by 16 downstream stories via the `rbac-checks` contract (`docs/requirements/auth.md`). Each check gates on `CurrentUser` (AUTH-01's session contract) and, where relevant, `persona` (AUTH-02's resolver), raising `HTTPException(403)` on denial — never UI-only hiding. Four structured JSON log events (`rbac_check_org_access`, `rbac_check_governance_visibility`, `individual_view_denied`, `member_view_denied`) record every check outcome with a fixed, PII-free field allowlist per event. A `PersonaResolutionError` from the resolver denies with 403 (fail-closed) rather than surfacing a 500. AC3's open-aggregate program-visibility model ships exactly as specified; the operational risk it carries (R-003) is recorded OPEN for `/arh-security-review`, not silently accepted.

## Constraints

- Python 3.11+, FastAPI 0.115, Pydantic 2.9 (existing stack, no version change).
- In-process only — no I/O, no external calls, no new runtime dependency (research: preflight confirms all toolchain pins already installed).
- Consumes AUTH-01's `session` contract (`CurrentUser: user_id, email, role, groups, programs`) and AUTH-02's `persona-resolver` contract (`async resolve(role: str) -> str`, raises `PersonaNotFoundError | PersonaResolutionError`) — both complete and live on `main`.
- Produces the `rbac-checks` contract (`docs/requirements/auth.md`) consumed by 16 downstream stories (AUTH-04, OVW-01..04, PGD-01..06, SHP-02..06): function names, parameter order, exception types, and log-event names are locked from this PRD forward. A post-Product-Gate rename requires a coordinated migration across every consumer.
- Dev-bypass sessions bypass RBAC entirely — out of scope here, owned by AUTH-01 (FR-AUTH-11).
- `app/core/logging.py`'s `JSONFormatter` merges `record.__dict__` extras correctly into the JSON payload (BED-02-FR-3, verified at `services/api/app/core/logging.py:55`); the four rbac log events depend on this. BED-02's earlier claim that extras were dropped does not carry forward — it was incorrect and is superseded by this verification.
- No UI surface: project-wide `integrations.design = html-mockup`, but AUTH-03 has no screens. `## Screen inventory` and a hi-fi `DESIGN.md` are not produced for this feature.

## Solution sketch

Five async functions in `app/core/rbac.py` — `org_access`, `program_visibility`, `individual_usage_visibility`, `member_in_program_visibility`, `governance_visibility` — each taking `current_user: CurrentUser` first, plus a `program_id` and/or `target_user_id`/`target_member_id` where the check needs one. A check either returns normally (authorized) or raises `HTTPException(status_code=403)` (denied). `org_access` and `governance_visibility` resolve persona via `app.state.persona_resolver.resolve(current_user.role)` and gate on persona membership in a fixed set; `program_visibility` is an open-aggregate pass-through requiring only an authenticated session; `individual_usage_visibility` and `member_in_program_visibility` gate on self-or-cio, the latter first requiring `program_visibility` to pass. A `PersonaResolutionError` from the resolver is caught at the call site and converted to a 403, logged at ERROR. Every check emits one of four structured JSON log events carrying only its allowlisted fields.

## Addressing Research Conditions

Research verdict: GO-WITH-CONDITIONS, 87/100, 5 numbered conditions from `docs/research/AUTH-03.md` § Verdict & Conditions.

- **C-1 (PersonaResolutionError handling)** — Settled: a `PersonaResolutionError` (Tier-3 Postgres timeout or connectivity failure) denies with `HTTP 403`, fail-closed, logged at ERROR level. Rationale: a resolver timeout is operationally indistinguishable from an unmapped role from the client's perspective, and denying matches AC4's fail-closed posture. Trade-off, stated plainly: a transient DB failure now presents to the client as an ordinary permissions error and does not invite a retry — see AUTH-03-FR-1 and the Reliability NFR below.

- **C-2 (exact per-event field allowlists)** — Settled, four fixed allowlists (see AUTH-03-FR-2): `rbac_check_org_access` and `rbac_check_governance_visibility` → `{user_id, persona, outcome, timestamp}`; `individual_view_denied` → `{user_id, target_user_id, outcome, timestamp}`; `member_view_denied` → `{user_id, program_id, target_member_id, outcome, timestamp}`. No email, no groups claim, no raw session context in any event.

- **C-3 (AC3 open-aggregate risk)** — Settled: AC3 is implemented exactly as specified (any authenticated session passes; `program_id` is not used for gating), inherited from the reference implementation per A-004. **R-003 stays OPEN**: any authenticated session can pass `program_visibility` for any `program_id`, so this check alone does not confirm program membership. Not accepted or closed at this PRD's Product Gate — flagged for `/arh-security-review` to re-examine against the downstream routes that come to rely on it. Downstream consumers must not read a passing `program_visibility` result as an affirmative "this program is in my list" — they must query `CurrentUser.programs` for roster questions. `program_visibility` is a veto gate, not a data source.

- **C-4 (outcome field semantics)** — Settled: the `outcome` field is one of the literal strings `"authorized"` or `"denied"` — never a boolean, never a free-text reason substituted for it.

- **C-5 (test-driven)** — Settled as a process commitment carried into Phase 2/3: the unit-test suite is written before implementation and covers all five checks' pass/deny branches, the AC5 (`member_in_program_visibility` → `program_visibility`) and AC7 (`governance_visibility` → `program_visibility`) cascading gates, an in/out enumeration over the hardcoded governance persona tuple, and a PII-audit test per log event asserting the payload key set equals its C-2 allowlist exactly — pattern: AUTH-02's `tests/unit/test_persona_resolver.py::test_persona_mapping_loaded_event_contains_no_pii_tc15`. Test-case authoring itself is out of scope for this PRD (`/arh-plan-requirements` Phase 2 / `/arh-plan-implementation`).

## Scope

**In:**
- `app/core/rbac.py` — five async check functions: `org_access`, `program_visibility`, `individual_usage_visibility`, `member_in_program_visibility`, `governance_visibility`.
- `PersonaResolutionError` → `HTTPException(403)` translation at every call site that resolves persona, logged at ERROR (C-1).
- Four structured log events with the field allowlists in AUTH-03-FR-2 (C-2).
- Hardcoded governance persona tuple `("architect", "product-manager", "developer")` — `cio` and `engineering-manager` excluded (AC6).
- AC5 cascading gate: `member_in_program_visibility` calls `program_visibility` first.
- AC7 cascading gate: `governance_visibility` calls `program_visibility` when a `program_id` is supplied.
- Locking the `rbac-checks` contract's function names, parameter order, exception types, and log-event names for the 16 downstream consumers.
- README documentation of the five checks, the four log events, and the fail-closed `PersonaResolutionError` policy.

**Out:**
- Dev-bypass RBAC exemption — owned by AUTH-01, FR-AUTH-11.
- Route wiring — deferred to each consuming story (AUTH-04, OVW-01..04, PGD-01..06, SHP-02..06); AUTH-03 ships pure-function checks with no routes of its own.
- Config-driven governance persona list — deferred; the hardcoded tuple is accepted for this story (research Risk #8). Promoting it to `Settings` + env var is a future story if ops needs to change it without a redeploy.
- Request-scoped persona-resolution memoization across multiple checks in a single request — deferred to a post-launch optimization story if cache-hit-rate monitoring (research Risk #4) shows it is needed.
- Any UI surface, `## Screen inventory`, or `DESIGN.md` — not applicable to this feature.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/AUTH-03.md` for canonical wording. New impl constraints introduced below (when any):

**AUTH-03-FR-1** — PersonaResolutionError vs. PersonaNotFoundError handling *(extends AC1, AC2, AC4, AC5, AC6, AC7 with: distinct exception handling and log level per exception type)*

Every call site that resolves persona catches `PersonaResolutionError` and `PersonaNotFoundError` separately (never a bare `except Exception`). `PersonaResolutionError` (Tier-3 timeout/connectivity failure) raises `HTTPException(status_code=403)` and logs the calling check's own `rbac_check_*` event with `outcome="denied"` at `logging.ERROR` — the resolver's own `persona_mapping_loaded` event (AUTH-02) is independent and unaffected. `PersonaNotFoundError` (all three tiers miss — an ordinary unmapped role) also raises `HTTPException(status_code=403)`, but logs at the check's normal `logging.INFO` level, since an unmapped role is a routine deny, not an operational failure.

**AUTH-03-FR-2** — Per-event log field allowlist *(extends the story's Observability NFR with: exact field set and outcome semantics per event)*

| Event | Fields | Outcomes logged |
|---|---|---|
| `rbac_check_org_access` | `{user_id, persona, outcome, timestamp}` | authorized + denied |
| `rbac_check_governance_visibility` | `{user_id, persona, outcome, timestamp}` | authorized + denied |
| `individual_view_denied` | `{user_id, target_user_id, outcome, timestamp}` | denied only |
| `member_view_denied` | `{user_id, program_id, target_member_id, outcome, timestamp}` | denied only |

`outcome` is the literal string `"authorized"` or `"denied"`. No event ever carries `email`, `groups`, JWT claims, session id, or request path. `program_visibility` (AC3) emits no event of its own — the open-aggregate check has no denial branch to log.

**AUTH-03-FR-3** — Governance persona set is a hardcoded module constant *(extends AC6/AC7 with: no config, no DB-driven list for this story)*

`_GOVERNANCE_PERSONAS: tuple[str, ...] = ("architect", "product-manager", "developer")` is a module-level constant in `rbac.py`, with a comment noting the deliberate contrast with AUTH-02's data-driven resolver: adding a persona to governance access requires a code change and redeploy, not a config edit, until a future story promotes it to `Settings`.

**AUTH-03-FR-4** — Cascading gate call order *(extends AC5/AC7 with: explicit, testable call sequence)*

`member_in_program_visibility` calls `program_visibility(current_user, program_id)` first; if it denies, `member_in_program_visibility` denies immediately without evaluating self-or-cio. `governance_visibility`, when invoked with a `program_id`, evaluates the persona gate (AC6) first; only if that passes does it call `program_visibility(current_user, program_id)`, and both must pass for the overall check to pass.

**AUTH-03-FR-5** — Locked downstream contract *(extends the story's Downstream Dependencies with: exact names, no post-hoc renames)*

The five function names — `org_access`, `program_visibility`, `individual_usage_visibility`, `member_in_program_visibility`, `governance_visibility` — are async, all take `current_user: CurrentUser` as the first positional argument, and are the names published in the `rbac-checks` contract (`docs/requirements/auth.md`). A rename after this PRD's Product Gate requires a coordinated migration across all 16 downstream consumers, not a silent signature change.

## Non-functional requirements

- Performance: each check adds `< 5ms p95` to request latency, in-process, no I/O — assumption logged in `docs/stories/AUTH-03.md` § Decision log (2026-08-26); the parent PRD's NFR-002 budgets only the whole request (≤2s).
- Security: Per `.claude/rules/security-baseline.md`: all five checks are enforced server-side only, never UI-only hiding. Dev-bypass sessions bypass RBAC entirely — out of scope (AUTH-01, FR-AUTH-11). **R-003 (OPEN)**: `program_visibility`'s open-aggregate model (AC3) passes any authenticated session for any `program_id`; flagged for `/arh-security-review`, not accepted or closed by this PRD. Downstream consumers must use `CurrentUser.programs` for roster questions, never a passing `program_visibility` call.
- Accessibility: N/A — backend library, no UI surface.
- Observability: four structured JSON log events per AUTH-03-FR-2. `rbac_check_org_access` and `individual_view_denied`/`member_view_denied` are NFR-011's original three-event set; `rbac_check_governance_visibility` was added 2026-08-31 by user decision, extending that set, and is already propagated to the `rbac-checks` contract in `docs/requirements/auth.md`. A PII-audit test per event (Phase 2/3, pattern AUTH-02 TC-15) asserts the payload key set equals the AUTH-03-FR-2 allowlist exactly.
- Reliability: fail-closed on every resolver error path — `PersonaResolutionError` and `PersonaNotFoundError` both deny (AUTH-03-FR-1); zero default-permit outcomes across all five checks.

## Visual spec

Not applicable — `integrations.design = html-mockup` but AUTH-03 has no UI surface (in-process check library only; the 16 downstream consumer stories own every route and screen that calls it).

## Rollout plan

- **Strategy**: bang-bang. AUTH-03 ships as a library with no route surface of its own; each of the 16 downstream stories independently gates its own route on importing it, so there is no phased-cohort rollout to coordinate at this layer.
- **Feature flag**: none — the library is always available once merged; downstream stories decide when to start calling it.
- **Backout plan**: revert the PR. No schema change, no data migration, no external dependency. If a downstream story has already merged and imports `rbac.py`, the backout sequence is the downstream story's revert first, then AUTH-03's.
- **Success signal**: the first downstream route wired against the library (AUTH-04) returns the expected 200/403 per check, and its `rbac_check_*`/`*_view_denied` log events appear with exactly the AUTH-03-FR-2 field sets — zero PII-audit-test failures.

## Documentation requirements

- **README updates**: `services/api/README.md` — new "RBAC checks" section (after the existing `/auth/*` API table), listing the five checks, their gating logic, the four log events with field allowlists, and the fail-closed `PersonaResolutionError` policy (AUTH-03-FR-1).
- **Runbook**: none — no configuration or operational lever beyond the code itself.
- **API reference**: N/A — internal library, not a route surface.
- **Inline code comments**: `app/core/rbac.py` module docstring covering the hardcoded governance persona tuple (AUTH-03-FR-3) and why it is hardcoded, the R-003 open-aggregate caveat on `program_visibility` (veto gate, not a roster source), and the `PersonaResolutionError`/`PersonaNotFoundError` fail-closed contract (AUTH-03-FR-1).
- **Examples / how-to**: none — `docs/requirements/auth.md` § rbac-checks already documents the call shape for the 16 downstream consumers.

## Open questions

Decisions logged in `docs/stories/AUTH-03.md` § Decision log.

## Approvals

- **2026-08-31** — Pratik Pawar (PO): **APPROVE**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs reviewed in `DESIGN.md`: N/A — `design = n/a`, backend-only feature (no UI surface)
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO-WITH-CONDITIONS (all 5 conditions addressed in § Addressing Research Conditions)
  - C-1 settled at gate: `PersonaResolutionError` → HTTP 403 fail-closed + ERROR log. Accepted trade-off: a transient Postgres failure presents to the client as a permissions error and does not invite a retry.
  - C-3 settled at gate: AC3 open-aggregate model confirmed as-specified per A-004. **R-003 remains OPEN**, flagged for `/arh-security-review` — explicitly not accepted or closed at this gate.
  - Test cases: 28 total, 28 automatable, `coverage_audit.uncovered=[]`
  - Tracker subtask: pratikpawar009/Dashboard#112
