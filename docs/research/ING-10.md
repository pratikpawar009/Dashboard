# Feasibility Assessment: ING-10 — POST /api/ingest/manifest

**Story**: ING-10 — POST /api/ingest/manifest — program identity + team roster ingest  
**Date**: 2026-09-08  
**Assessor**: Claude Code  

---

## Exploration Log

### Upstream dependencies

- **Reads** `docs/requirements/{api,data,auth}.md`, confirmed binding contracts exist.
- **ING-01** (`ingest-token-auth`): `app/core/ingest_auth.py` — bearer token validation, scope check (401/403) — shipped, tested.
- **BED-01** (`db-schema`): `services/api/app/models/{rollup,ingestion}.py` — 18 existing tables, ProgramSummary model available for identity upsert.
- **BED-03** (`rollup-rebuild`): `app/services/rollup_rebuild.py:360,370` — verified that `ProgramMembers` is unconditionally deleted/rebuilt from `usage_events` with no prior-state carry-forward, confirming the RTM decision to create a separate `program_roster` table.

### New schema required

- **program-roster-schema** does not exist. New migration (003_program_roster.py) required to create the `program_roster` table.
  - Fields: `id, program_id, email, name, role, source='file', removed_at (nullable), created_at, updated_at`
  - Constraint: `unique(program_id, email)`
  - Soft-delete via `removed_at`, not hard DELETE.

### Existing patterns to follow

- **Router pattern**: `app/api/*.py` — one APIRouter per resource, thin handlers calling business logic layers (see `app/api/personal_usage.py`, `app/api/activities.py`).
- **Auth dependency**: `Depends(get_ingest_token(program_id))` — already wired and tested in `app/core/ingest_auth.py`.
- **Schema validation**: Request/response models in `app/schemas/*.py` (Pydantic v2, separate In/Out models; see `app/schemas/personal_usage.py` precedent).
- **Error handling**: Reuse `app/core/errors.py`'s envelope (HTTPException → `{"error": {"code", "message", "details"}}`). Four failures: AC-1 (401/missing-revoked-expired), AC-2 (403/scope), AC-5 (400/bad enum), AC-8 (413/oversized).
- **Logging**: Structured JSON via `logger.info()` with `extra` dict. Never log emails or names — only opaque identifiers (`program_id`, counts).
- **Response codes**: `200` on success (precedent: ING-02/ING-03 sibling ingest endpoints, story AC-3).

### New files to create

1. **Migration**: `services/api/migrations/versions/003_program_roster.py` — create `program_roster` table.
2. **ORM model**: `app/models/roster.py` — SQLAlchemy `ProgramRoster` class.
3. **Request/response schemas**: `app/schemas/manifest.py` — `ProgramIdentity`, `TeamMember`, `ManifestIn`, `ManifestResponse`.
4. **Business logic service**: `app/services/manifest_ingest.py` — upsert identity, expand aliases, validate roles, soft-delete removed members, build response.
5. **Role mapping**: `app/core/role_map.py` — 6-way slug → persona role mapping table (assumption in story Decision log, accepted).
6. **Route handler**: Add `POST /api/ingest/manifest` to `app/api/ingest.py` or create `app/api/manifest.py`.
7. **Frontend token update**: `apps/web/src/lib/programStyle.ts` — add `Upgradation` key to `PROGRAM_TYPE_COLORS` (folded AC-10).

### Shared code at risk

- **ProgramSummary** model (`app/models/rollup.py:64-86`) — upsert depends on existing table; `type` field must accept all 5 enum values (`Greenfield|Brownfield|Upgradation|Migration|Maintenance`), per manifest enum, RTM decision 2026-09-08. No validation exists on this model today — story must add it.
- **Alembic migration chain** — 003 must come after 002 (`002_personal_usage_indexes.py`). Migration auto-registers via `versions/` directory.
- **UserRole model** (`app/models/ingestion.py:104-112`) — existing `email` PK, row created/updated by manifest ingest with `source='file'`. Must support alongside Keycloak-written rows (`source='keycloak'`).
- **HTTPBearer instance** in `ingest_auth.py` — not shared with user-auth (`auth.py`), per FR-6 isolation. No risk.

### Decisions already settled (per RTM 2026-09-08, not to re-open)

1. `program_roster` is a new table, NOT `program_members` (which is wiped by rollup rebuild).
2. Soft-delete via `removed_at`, never hard DELETE.
3. Every alias in `aliases[]` gets its own row — usage joins on `usage_events.user`, matching `git config user.email`.
4. Role mapping is an in-process module-level table (scope: ING-10 only; ING-08 wiring deferred).
5. Canonical `.harness` layout: committed `program.yaml` (carries `programId`, `program:`, `team[]`); local/gitignored `profile.yaml` (self-check, never trusted).
6. File is authoritative (opposite of CIO Dashboard Project prior art).
7. Program type enum: `Greenfield|Brownfield|Upgradation|Migration|Maintenance` (authoritative; `programStyle.ts` widening is folded AC-10).
8. `push_manifest` transport (MCP/CLI, ING-04/ING-06) is deferred; `program-manifest-api` has `consumed_by: []` deliberately.

### Known open assumptions (AC, story, or Decision log)

- **Upgradation color hex** (AC-10, Decision log 2026-09-08): `#0f9b8e` (color) / `#e6f3f2` (background) — no source given; chosen to match `Greenfield` saturation/scheme precedent.
- **Team size cap** (AC-8, Decision log): 500 raw entries before alias expansion, `413` over — sized between ING-03 (<300ms) and ING-02 (<3s), no explicit PRD budget.
- **Performance budget** (NFR, Decision log): p95 < 500ms for 500-entry roster — assumption, no PRD budget given.
- **Observability event** (NFR, Decision log): `ingest_manifest_write` — extends `ingest_write_completed`/`ingest_artifacts_write` naming precedent; NFR-011's event set does not name it.
- **Validation atomicity** (AC-5, AC-6, Decision log): `program:` enum/schema failures abort whole request (400); `team[]` per-member failures (unknown role) reject only that member (partial commit) — assumption, modeled on ING-02 precedent.
- **Re-added member un-remove** (AC-7, Decision log): re-push whose `team[]` includes a previously soft-deleted email resets `removed_at` to `null` — assumption, treating manifest as authoritative on every push.

---

## Pattern map

### Existing code to extend

- **`app/api/ingest.py`** — add `POST /api/ingest/manifest` route handler; router already defined and skeleton in place (currently holds only `/events` endpoint, which also remains).
- **`app/models/rollup.py`/`app/models/ingestion.py`** — `ProgramSummary` and `UserRole` models are already present; no model changes needed (new `ProgramRoster` model goes in its own file).
- **`app/core/ingest_auth.py`** — already implemented and tested; no changes needed, only consumed as a dependency.

### Existing patterns to follow

1. **Router patterns** (`app/api/*.py`): Thin handlers calling service layer, not business logic in routes.
   - Example: `app/api/personal_usage.py` (line ~30) calls `await personal_usage.get_usage_summary(...)`.
   
2. **Pydantic schema pattern** (`app/schemas/*.py`): Separate In/Out models for request/response.
   - Example: `app/schemas/personal_usage.py` has `PersonalUsageIn` and `PersonalUsageResponse`.
   
3. **Service layer pattern** (`app/services/*.py`): Async functions taking `AsyncSession`, no service classes (yet).
   - Example: `personal_usage.py:get_usage_summary()`, `rollup_rebuild.py:rebuild_program_rollups()`.
   
4. **Error handling** (`app/core/errors.py`): HTTPException raised in routes/services, caught by registered handlers.
   - Envelope: `{"error": {"code": "http_XXX", "message": "...", "details": null}}`.
   
5. **Logging** (`app/core/logging.py`): Structured JSON, `extra` dict for fields, never PII.
   - Example: `logger.info("event_name", extra={"field1": val1, ...})`.

6. **Dependency injection** (FastAPI `Depends`): `get_ingest_token()`, `get_db()` are already wired.

### New files to create (best-guess, refined in plan-implementation)

| File | Purpose |
|------|---------|
| `services/api/migrations/versions/003_program_roster.py` | Alembic migration: create `program_roster` table |
| `services/api/app/models/roster.py` | SQLAlchemy ORM: `ProgramRoster` model |
| `services/api/app/core/role_map.py` | In-process role slug → persona mapping table |
| `services/api/app/schemas/manifest.py` | Pydantic: `ManifestIn`, `ManifestResponse`, `IdentityResponse`, `RosterMemberResponse` |
| `services/api/app/services/manifest_ingest.py` | Business logic: identity upsert, alias expansion, role validation, soft-delete, response building |
| `services/api/app/api/manifest.py` OR extend `services/api/app/api/ingest.py` | Route handler: `POST /api/ingest/manifest` |
| `apps/web/src/lib/programStyle.ts` (edit existing) | Add `Upgradation` key to `PROGRAM_TYPE_COLORS` (folded AC-10) |
| `services/api/tests/unit/test_manifest_ingest.py` | Auth (401/403), validation (400/413), upserts, soft-delete, role rejection |
| `services/api/tests/unit/test_role_map.py` | Role slug mapping coverage (6 slugs → 5 personas, plus unknown-slug case) |

### Shared code at risk — ripple points

1. **`ProgramSummary` type field** — must support 5-value enum (`Greenfield|Brownfield|Upgradation|Migration|Maintenance`).
   - Risk: If `type` validation is added anywhere (e.g., validators on ProgramSummary), the schema update could fail if it doesn't include all 5.
   - Mitigation: Validation lives only in `manifest_ingest.py:_validate_program_type()`, not on the model itself (Pydantic-only, no schema-level CHECK constraint).

2. **Alembic migration ordering** — 003 must follow 002 (`002_personal_usage_indexes.py`).
   - Risk: If another story lands a 003 migration in parallel, merge conflict and manual sequencing required.
   - Mitigation: Coordinate with feature branch merges; Alembic's linear chain (down_revision linking) enforces order.

3. **`ingest_tokens` table** — already supports program-scoped auth via `allowed_program_ids`.
   - Risk: None — auth dependency is stable; no changes needed.

---

## Risk register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Integration | HIGH | **PII logging violation**: email/name fields are PII, must never reach logs. Story touches trust boundary (untrusted manifest JSON input). | (a) Add lint/test rule to catch string literals `email`/`name` in log statements (`extra` dict); (b) Code review emphasis on `.claude/rules/security-baseline.md` compliance; (c) Use `logger.debug()` in dev, `logger.info()` in prod only for opaque counts. |
| 2 | Domain | HIGH | **Partial-commit semantics ambiguous (AC-5 vs AC-6)**: AC-5 says `program:` enum failure aborts whole request (400); AC-6 says `team[]` role-slug failure rejects only that member. Story Decision log adopts ING-02 precedent (mix-of-valid/invalid commits partially), but PRD Functional Expectation §1 says "one payload/one transaction" — could mean all-or-nothing. | Re-read PRD FE §1 in plan phase; if ambiguity remains, escalate to user for AC clarification (decision already recorded in story, but warrant explicit confirmation during planning). Implement per recorded assumption (partial commit), test both cases. |
| 3 | Integration | MED | **Role mapping table has no persistence contract**: 8-value mapping (dev→developer, etc.) is an author assumption, accepted as-is by user, but scoped to ING-10 only — no RTM row, no persistent store. ING-08 (Keycloak writer) will need to wire onto it, which is an undecided scope change to a shipped story. | (a) Implement in-process mapping as `app/core/role_map.py`, exportable for ING-08; (b) Consider adding a `role_mapping` table in migration 003 (parallel to `persona_config`), even if not used by ING-10 yet — positions ING-08 to wire in without another migration; (c) Document assumption + forward path in PLAN/DECISIONS. User accepted keeping it in-process for now. |
| 4 | Compatibility | MED | **Upgradation color hex is an author assumption**: `#0f9b8e`/`#e6f3f2` chosen without design confirmation. Decision log notes it as assumed (2026-09-08). | (a) Code-review & design validation before merge; (b) No risk to backend (manifest API doesn't validate hex, only accepts enum value); (c) Frontend AC-10 (color-map widening) can be tested in isolation with a fixture value, then updated if design changes hex. |
| 5 | Domain | MED | **Alias expansion cardinality**: Story says "every alias gets its own row"; N aliases + primary = N+1 rows. No explicit cap on alias count; AC-8 caps total `team[]` entries at 500, so aliases are included in that cap. If a single person has 100 aliases, expansion cost is O(1) per row but storage/query becomes expensive. | (a) No code change needed (story doesn't add secondary limits); (b) Document in DECISIONS that alias expansion is bounded by AC-8's 500-entry cap, not a per-person alias limit (implicit); (c) Test with fixture carrying max-alias scenario to confirm sub-500ms latency. |
| 6 | Security | MED | **Email validation on manifest input**: Story does not specify email format validation (RFC 5322, vs simpler length/presence check). `team[].email` is user input at trust boundary. If stored verbatim without validation, invalid emails could land in `program_roster` and break downstream matching (AUTH-06 session.email matching). | (a) Validate email format at schema layer (Pydantic `EmailStr` or regex, per `app/schemas/*.py` precedent); (b) Reject with 400 if format invalid (AC-5 whole-request abort pattern); (c) Test with valid/invalid email fixtures. Story ACsl do not explicitly list email-format failure as a case, so validate silently (no separate response bucket). |
| 7 | Performance | MED | **p95 < 500ms budget is untested assumption**: No explicit NFR budget given; positioned between ING-03 (<300ms) and ING-02 (<3s). Depends on DB query perf (identity upsert, roster upsert, removal soft-delete), alias expansion loop (O(team_size × aliases_per_member)), role validation (6-way lookup), and rollup rebuild (not called by ING-10, unlike ING-02). | (a) Implement service layer with explicit query bounds (single batch upsert for identity, single batch upsert for roster with ON CONFLICT handling); (b) Benchmark with 500-entry fixture + 3-alias-per-person scenario; (c) If p95 > 500ms, reduce AC-8 cap or optimize queries before production merge. |
| 8 | Dependency | MED | **UserRole table dual-source ownership**: ING-10 writes `source='file'`, ING-08 (shipped, validated) writes `source='keycloak'`. No conflict expected (distinct sources), but a read-path query must filter correctly if it cares about source. AUTH-06 reads `program_roster` (separate table), not `user_roles`, so no direct risk, but any future query mixing both sources must be aware. | (a) Document in DECISIONS that `user_roles` is now dual-sourced (file + Keycloak); (b) Any future query over `user_roles` must handle `source` field explicitly; (c) No code change needed; ING-10 writes `source='file'`, ING-08 writes `source='keycloak'` — both already scoped. |
| 9 | Integration | LOW | **Repo's own `.harness/profile.yaml` is non-conforming**: Current file is committed and holds `files`/`artifacts` with no `program:` or `team[]`. RTM 2026-09-08 notes this touches ING-06's dogfooding path. Story does not own fixing it, but a `/api/ingest/manifest` request from this repo's own CI will fail until profile is migrated to canonical two-file layout. | (a) Not a blocker for ING-10 itself (endpoint works for external programs); (b) Document carry-forward for ING-06 (when it gains `push_manifest` support); (c) Manual one-time fix: create `.harness/program.yaml` with canonical schema, move identity/team to it, rename `profile.yaml` to `.gitignore` it. |
| 10 | Domain | LOW | **program_members name/role enrichment deferred**: `program_members` rows (used by PGD-05 Team panel) will not have roster name/role after ING-10 ships, since rollup rebuild sources them from `usage_events.user` (opaque ID) only. Same pre-existing gap as before. Enriching them from `program_roster` is a real follow-on but is NOT in PRD FE, so stays carry-forward. | (a) Not a story blocker — only affects PGD-05 UX; (b) Document carry-forward: "PGD-05 team panel rows (from `program_members`) will show usage-event identifiers, not roster names/roles, until a follow-on story enriches them from `program_roster`"; (c) User confirmed not in scope. |

---

## Scoring

| Dimension | Weight | Score | Reasoning |
|-----------|--------|-------|-----------|
| **Integration** | 25 | 70 | Upstream dependencies (`ING-01`, `BED-01`, `BED-03`) are shipped & tested. Trust-boundary PII handling (email/name logging) is a HIGH risk (R-1) but mitigated by lint + code review + precedent (personal-usage.py avoids PII). Role mapping is in-process only (scoped, no persistence contract gap for ING-10, though ING-08 wiring is undecided). 70 reflects high risk to ship if PII logging makes it in, balanced by clear mitigation path. |
| **Compatibility** | 20 | 80 | No backwards-compat concerns (new endpoint, new table, isolated from existing rollups). `programStyle.ts` widening is additive, no breaking changes. Upgradation color assumption is cosmetic (MED risk R-4, resolved by code review). 80 reflects confidence in isolated change surface. |
| **Domain** | 20 | 65 | Partial-commit semantics (R-2, HIGH) is the primary risk — AC-5 vs AC-6 wording could be read both ways. Alias expansion cardinality (R-5, MED) and email validation (R-6, MED) are clear and testable. 65 reflects unresolved AC ambiguity; if clarified in planning, score rises to 75+. |
| **Performance** | 15 | 75 | p95 < 500ms is untested assumption (R-7, MED), but service design (batch upserts, O(N) alias loop, 6-way role lookup) is aligned with budget. DB query perf depends on Postgres optimization (indexes on `program_id`, `email`); no unbounded fan-out. Benchmarking required pre-ship. 75 reflects medium confidence; optimization path clear if needed. |
| **Dependency** | 20 | 80 | ING-01 (auth) is complete. BED-01 (schema) is complete. BED-03 (rollup rebuild) is complete and verified to NOT conflict. No blocking external dependencies. UserRole dual-source (R-8, MED) is a design note, not a blocker. 80 reflects solid upstream alignment. |

**Total: (70×0.25) + (80×0.20) + (65×0.20) + (75×0.15) + (80×0.20) = 17.5 + 16 + 13 + 11.25 + 16 = 73.75**  
**Normalized: 74/100**

---

## Verdict

**GO-WITH-CONDITIONS**

The story has solid upstream dependencies, clear contracts, and well-established patterns to follow. However, two MED-to-HIGH domain risks require explicit plan-phase attention:

1. **Partial-commit semantics (AC-5 vs AC-6)**: PRD Functional Expectation §1 says "one transaction" but is ambiguous on partial-failure handling. Story Decision log and ING-02 precedent suggest per-member rejection with identity/valid-roster commit. **Plan must explicitly confirm this is the intended behavior**, and implementation must test both paths.

2. **PII logging (email/name in logs)**: Story touches untrusted input at trust boundary. Security-baseline rule forbids PII logging. **Plan must include lint rule / code-review checklist to catch this violation before merge.**

Both are mitigatable in planning without re-scoping. Go to `/arh-plan-requirements` with explicit attention to these two points.

### Conditions for GO-WITH-CONDITIONS

- [ ] **Plan-phase requirement C-1**: Confirm AC-5/AC-6 partial-commit semantics with user (not the assessor); update story's AC wording or DECISIONS if ambiguity exists.
- [ ] **Plan-phase requirement C-2**: Add PII logging lint rule or code-review emphasis in PLAN; spot-check manifest_ingest.py service layer for any `email`/`name` in logger statements (not just `extra` dict).
- [ ] **Plan-phase requirement C-3**: Confirm Upgradation color hex (`#0f9b8e`/`#e6f3f2`) with design; update `programStyle.ts` AC-10 fixture if design changes.

---

## Synthesis

ING-10 is a well-scoped ingest endpoint adding program identity and team-roster sourcing from each program's committed `.harness/program.yaml`. The story has complete upstream contracts (ING-01 auth, BED-01 schema, BED-03 rebuild rules verified not to conflict), established patterns to follow across request/response schemas, service layers, and logging, and RTM-settled decisions on roster table design (separate from program_members, soft-delete removal, alias expansion). The primary risks are domain-level: partial-commit semantics for invalid team members (AC ambiguity, mitigated by ING-02 precedent and plan-phase confirmation) and PII logging at the trust boundary (email/name fields, mitigated by lint + code review). Performance budget (p95 < 500ms for 500-entry roster) is untested but design aligns: batch upserts, O(N) alias loop, 6-way role lookup fit within budget. The score of 74/100 reflects solid integration and dependency alignment offset by moderate domain and performance uncertainty—both addressable in planning without re-scoping. Proceed to `/arh-plan-requirements` with Conditions C-1 (partial-commit clarification), C-2 (PII logging lint), and C-3 (color-hex design review).

---

## Recommendations for Planning

1. **Immediate (planning phase)**:
   - Confirm AC-5/AC-6 partial-commit semantics: Is `program:` enum failure a whole-request abort (400), and `team[]` role-slug failure a per-member rejection (partial commit)? If yes, this aligns with ING-02 precedent; if no, AC wording needs update.
   - Lock Upgradation color hex with design team before AC-10 implementation.
   - Add lint rule to catch `email`/`name` string literals in `logger.*()` calls (or code-review checklist if lint is infeasible).

2. **Implementation phase**:
   - Batch upsert for `program_summary` (identity) and `program_roster` (roster, handling soft-delete removal).
   - Use `ON CONFLICT (program_id, email) DO UPDATE` pattern in Alembic/ORM.
   - Validate email format at Pydantic schema layer (EmailStr or regex).
   - Benchmark manifest_ingest.py with 500-entry + 3-alias fixture; if p95 > 500ms, optimize or reduce AC-8 cap.
   - Test alias expansion, role-slug validation (unknown slugs → rejection bucket), and soft-delete removal + un-removal on re-push.

3. **Carry-forward**:
   - This repo's own `.harness` migration to canonical two-file layout (touches ING-06).
   - program_members enrichment from program_roster name/role (deferred, noted for PGD-05).

---

## Open Clarifications

**RESOLVED 2026-09-08 — none open.**

~~AC-5 vs AC-6 partial-commit semantics~~ — resolved as **two-tier validation**: request-level
failures (`program:` schema/enum) abort the whole request with `400` and zero writes; row-level
failures (a `team[]` entry's `role` slug) reject that entry's rows only, while the identity write
and every other valid entry commit.

Two corrections to how this was originally raised:

1. **The citation was wrong.** This clarification rested on "PRD Functional Expectation §1 says
   'one transaction'". `docs/prd/roster-sourced-program-membership.md` contains no occurrence of
   `transaction`, `atomic`, or `all-or-nothing` — grep-verified. The phrase existed only in
   AC-5's own tail, which has since been reworded because "the request is one transaction" read
   as though it governed row-level failures too.
2. **AC-5 and AC-6 were never contradictory** — they describe two different failure classes, which
   is a coherent and common design.

The question underneath was still worth asking, because the two-tier split was an author
assumption (cited as "precedent from ING-02"), never a user decision. It was settled on evidence:
`program-manifest-api`'s already-frozen `response` field specifies "received/valid/rejected counts
per section (identity, roster), plus per-email created/updated/skipped and rejection reasons" — a
per-email created/updated/skipped/rejected breakdown is meaningless under all-or-nothing, where
every response is either wholly applied or a bare `400`. All-or-nothing would have required
amending that contract, not just the AC. See `docs/stories/ING-10.md` § Decision log.

---

## State write (mandatory, unconditional)

```json
{
  "research": "complete",
  "research_verdict": "GO-WITH-CONDITIONS",
  "phase": "research",
  "last_updated": "2026-09-08T00:00:00Z"
}
```

(Timestamp is placeholder; actual time written by state-sync logic in orchestrator.)
