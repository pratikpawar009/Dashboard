# PLAN: ING-02 — POST /api/ingest/files — activity ingest

Status: Complete

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Three entries: D-01 (`rebuild_org_rollups()` runs out-of-band from the request path via FastAPI `BackgroundTasks` — supersedes BED-05 D-05's ordering write-up for ING-02, promoted to ADR-0012 because it changes the shared `rollup-rebuild` `commit_boundary_note` that ING-04/ING-06/ING-09 will inherit); D-02 (stub cleanup + orphan handling + skill citation retarget ship in the same PR as router registration — closes carry-forward risks R-10 and BED-05 R-09); D-03 (envelope-`kind` vocabulary lives in one shared module `services/api/app/core/ingest_kind.py`, on the `app/core/role_map.py` model, so ING-03's `"artifacts"` extends the same file). One new ADR under `docs/adr/` this story: `ADR-0012` (index entry added).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`. 24 entries: 15 create, 7 modify, 2 delete. No `generate` or `external` entries. Every `F-NN` is referenced by ≥1 task's `files[]`; every consumer of a `create` entry (except test/migration leaves) has a matching `modify` wiring entry (see § Module hierarchy).

### Module hierarchy

```
services/api/app/api/
├── ingest_files.py                                (new — F-01)
│   - input:  raw JSON body {program_id, kind, rows[]} + Authorization: Bearer <token>
│   - output: 200 IngestFilesResponse | 400 | 401 | 403 | 404 | 413
│   - public: router = APIRouter(prefix="/api/ingest", tags=["ingest-files"])
│             @router.post("/files", status_code=200, response_model=IngestFilesResponse)
│             async def push_files(request, background_tasks, credentials, db) -> IngestFilesResponse
│   - internals: manual `await get_ingest_token(program_id=..., credentials=..., session=db)`
│                (mirrors app/api/manifest.py verbatim in shape — FR-5 / C-4);
│                fresh private `HTTPBearer(auto_error=False)` instance per module
│                (never imports ingest_auth.py's `_http_bearer` — FR-5);
│                request-tier checks: JSON body dict, program_id str, envelope kind via
│                `accept_envelope_kind()` (400 if reject — FR-7 / AC-4 tier),
│                `len(rows) > 5000` → 413 (AC-4); then delegates to `activity_ingest.ingest_files()`;
│                schedules `dispatch_org_rebuild()` via `background_tasks.add_task(...)` (D-01 / ADR-0012)
│
└── ingest.py                                      (deleted — F-09; unregistered ING-02 stub, FR-6 / C-5)

services/api/app/services/
└── activity_ingest.py                             (new — F-02)
    - input:  db: AsyncSession, program_id: str, payload: dict, token_label: str, on_org_rebuild: Callable
    - output: IngestFilesResponse
    - public: async def ingest_files(db, program_id, payload, token_label, on_org_rebuild) -> IngestFilesResponse
              def elapsed_ms(start: float) -> int
              def log_ingest_write_completed(**allowlisted_kwargs) -> None
    - internals:
        _MAX_ROWS_PER_INSERT = 2_730                                (FR-2 — const, floor(65_535 / 24 cols))
        _ENVELOPE_ROW_CAP    = 5_000                                (AC-4 defence-in-depth; router also enforces)
        _ROW_SCHEMA_COLUMN_MAP = {...}                              (FR-4 wire→column alias table, C-3)
        _validate_rows(rows) -> (valid_rows, rejected)              (per-row ActivityRowIn.model_validate)
        _dedup_intra_batch(valid_rows) -> (dedup_rows, dedup_rejected)  (FR-3 / C-2, last-wins)
        _chunk_upsert(session, dedup_rows) -> (inserted_ct, updated_ct)  (FR-2 / C-1, chunked pg_insert)
        program-scope rebuild call inline via `rebuild_program_rollups(session, program_id)` (BED-05, unchanged)
    - PII discipline: `log_ingest_write_completed` allowlist = {event, program_id, rows_received,
                      rows_inserted, rows_updated, rows_rejected, duration_ms} — FR-8 / C-7

services/api/app/schemas/
├── ingest_files.py                                (new — F-03)
│   - input:  none (defines Pydantic models)
│   - output: ActivityRowIn, IngestFilesResponse, SectionCounts, RejectionEntry
│   - public: `ActivityRowIn`  (per-row model; `field_validator`s per FR-4 — raise on malformed_iso_date,
│              missing_required_field; unknown fields silently dropped per FR-4 / Q-01)
│             `RejectionEntry {index: int, reason: str}`  — never row content (FR-8 / C-7)
│             `IngestFilesResponse {received, valid, inserted, updated, rejected: list[RejectionEntry],
│                                   rollup_summaries: dict}`
│
└── activity.py                                    (deleted — F-10; orphan after F-09, D-02 / FR-6 / C-5)

services/api/app/core/
└── ingest_kind.py                                 (new — F-04, D-03)
    - input:  a candidate envelope kind string
    - output: bool (accepted?)
    - public: `_ACCEPTED_KINDS: frozenset[str] = frozenset({"activity"})`  (ING-03 extends to {"activity", "artifacts"})
              `def accept_envelope_kind(kind: str) -> bool`
    - shape:  matches `app/core/role_map.py`'s single-module-owns-vocabulary discipline

services/api/app/main.py                           (modified — F-08)
    Replaces the 11-line `# `ingest_router` is deliberately NOT registered` comment at :78-88
    with `from app.api.ingest_files import router as ingest_files_router` (top imports)
    and `app.include_router(ingest_files_router)` (grouped with other includes). Closes
    BED-05 carry-forward R-09.

services/api/app/models/ingestion.py               (modified — F-06)
    `UsageEvent` gains two Mapped columns:
      `source:           Mapped[str | None] = mapped_column(String, nullable=True)`
      `copilot_credits:  Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)`
    Matching the additive migration below. Schema-diff gate
    (`tests/test_migrations.py::TestSchemaDiffGate`) requires model + migration to agree.

services/api/migrations/versions/
└── 006_usage_events_source_credits.py             (new — F-05)
    revises 005_persona_precedence (current head).
    upgrade():   op.add_column("usage_events", sa.Column("source", sa.String(), nullable=True))
                 op.add_column("usage_events", sa.Column("copilot_credits", sa.Numeric(), nullable=True))
    downgrade(): op.drop_column("usage_events", "copilot_credits")
                 op.drop_column("usage_events", "source")
    Alembic self-registers via `down_revision = "005_persona_precedence"` (matches 002/003/004/005
    precedent — no separate registry file needs editing).

services/api/tests/ (unit + perf — no tests/integration/ dir per docs/config/project-commands.yaml)
├── test_migrations.py                             (modified — F-07; assert both columns exist after 006, absent after downgrade)
├── unit/
│   ├── test_activity_ingest_alias_mapper.py       (new — F-11, FR-4 gap #1)
│   ├── test_activity_ingest_chunk_ceiling.py      (new — F-12, FR-2 / C-1 bind-param ceiling)
│   ├── test_activity_ingest_intra_batch_dedup.py  (new — F-13, FR-3 / C-2)
│   ├── test_ingest_kind.py                        (new — F-15, FR-7 envelope allowlist)
│   ├── test_ingest_files_pii_logging.py           (new — F-16, C-7 / FR-8 — mirrors test_manifest_pii_logging.py)
│   ├── test_ingest_files_route_registered.py      (new — F-17, FR-6 boot smoke — gap #2, follows
│   │                                                the app.routes-inspection precedent from
│   │                                                test_auth_oidc_login.py:184 / test_auth_logout.py:199)
│   ├── test_ingest_files_idempotency.py           (new — F-18, ING-02-TC-01 / #293)
│   └── test_ingest_files_auth_denial.py           (new — F-19, ING-02-TC-02 / #294)
└── perf/
    └── test_ingest_files_perf.py                  (new — F-20, NFR-performance gap #3, C-10;
                                                    seeds usage_events to 20k/40k/160k rows across
                                                    ≥3 programs before the 5000-row push; module
                                                    docstring records seeded sizes + per-size p95
                                                    budget per Research Rec #1)

docs/requirements/
├── api.md                                         (modified — F-21, C-3)
│   `### ingest-files-api` section's `shape:` gets the full `rows[]` field list:
│   raw field names + the 5 aliases (Q-01) + types (per db-schema) + unknown-field policy
│   (dropped silently, row still commits per FR-4 / Q-01).
│
└── data.md                                        (modified — F-22, C-11 + ADR-0012)
    `### rollup-rebuild` `invariant:` — replace the "O(events for the affected program) per write"
    clause with the corrected wording (org rebuild is O(all events); program rebuild is O(events for
    the affected program)) per BED-05 DATA-DESIGN.md:54's own contradiction of the current line.
    `commit_boundary_note:` — update to reflect ADR-0012 (org rebuild is dispatched out-of-band as
    a FastAPI BackgroundTask; the caller-side ordering ING-02 implements is: (1) commit usage_events,
    (2) sync rebuild_program_rollups, (3) enqueue rebuild_org_rollups).

.claude/skills/pydantic-patterns/SKILL.md          (modified — F-14, D-02)
    Six citations to `app/schemas/activity.py` (deleted in F-10) are retargeted to
    `app/schemas/ingest_files.py` (new in F-03) — same in/out split pattern, canonical example
    now points at a shipped, registered module.

services/api/README.md                             (modified — F-23, Docs T2)
    API table gets `POST /api/ingest/files` entry beside `POST /api/ingest/manifest` (ING-10
    precedent).

README.md                                          (root, modified — F-24, Docs T2)
    Root API table mirrors the same one-line entry (PRD Documentation § README updates).
```

Navigation / routing map — N/A. Backend-only endpoint; a route → component map is not applicable. The one route added is `POST /api/ingest/files` served by `push_files` in `ingest_files.py` (see the module hierarchy above); the in-process background dispatch (`dispatch_org_rebuild`) is described in `DATA-DESIGN.md` § 10 Async & messaging, not here.

## 3. Module Hierarchy

See the tree in §2. Wiring summary:

- Every `create` production module has a matching `modify` consumer entry in the file plan: `F-01` (router) ← `F-08` (`app/main.py` include); `F-02` (service) ← `F-01` (router import); `F-03` (schemas) ← `F-01` + `F-02` imports; `F-04` (ingest_kind) ← `F-01` import. Model additions in `F-06` are consumed by `F-02` (chunked upsert reads `UsageEvent.__table__.columns`) and by the schema-diff gate `F-07`.
- `F-05` (migration 006) self-registers via its own `down_revision = "005_persona_precedence"` — Alembic-discovered, no separate registration file needs editing (matches 002/003/004/005 precedent).
- Every new test file is a leaf per `plan-validation`'s wiring exception.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. 18 tasks (T-01..T-18): 9 S, 6 M, 3 L. Every `file_plan` entry (F-01..F-24) is covered by ≥1 task; no two DAG-independent tasks share a file (verified — zero write conflicts).

**Ordering constraints (mandatory, not advisory)**:

- **T-01 (additive migration + model + schema-diff assertion) has no predecessors and MUST land first** — every downstream `activity_ingest` task (T-04) reads the model's post-migration column count (24) to derive `_MAX_ROWS_PER_INSERT`, and T-08's bind-ceiling assertion reads `len(UsageEvent.__table__.columns)` at runtime. If the model change lands after `activity_ingest`, the chunk constant is derived against the wrong column count and the ceiling assertion is meaningless.
- **T-06 (stub cleanup, orphan deletion, SKILL.md retarget, router wiring in `app/main.py`) MUST land in one PR** (D-02): a partial cleanup leaves an orphaned import or a stale citation and the CI review would fail on either half.
- **T-16 (write `api.md#ingest-files-api` rows[] field list) is a blocking write** for ING-04/06/09 — the shared contract, not this feature's private spec. It depends only on T-03 (the schema module fixes the wire→column alias set).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/ING-02.md` § Risk register. Risks 1, 2, 3, 6, 9 are marked RESOLVED in the research doc itself (BED-05 shipped) — not re-cited here. The 4 remaining HIGH/MED risks are all addressed by tasks; 1 LOW risk is accepted (carry-forward to ING-01, not this story's owner).

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-04    | HIGH     | T-04, T-08   |
| R-05    | HIGH     | T-04, T-09   |
| R-07    | MED      | T-16         |
| R-08    | MED      | T-02, T-10   |
| R-10    | MED      | T-06         |
| R-11    | MED      | T-04, T-11   |
| R-12    | LOW      | T-13         |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale                                                                                                                                                                                                                             |
|---------|----------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| R-13    | LOW      | `ingest_tokens.last_used_at` never updated — out of scope (ING-01 owns token lifecycle); research doc explicitly flags this as ING-01's concern, not ING-02's. Revisit when ING-01 revisits the token lifecycle.                       |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

The PRD `## Addressing Research Conditions` section carries the FR-level mapping. Task-level mapping below.

| Cond  | Condition (abbreviated — see `docs/features/ING-02/REQUIREMENTS.md` § Addressing Research Conditions) | Addressed by |
|-------|-----|--------------|
| C-1   | Chunked upsert at named constant ≤ 2,978; bind-param ceiling assertion in a test.                                | T-04, T-08 |
| C-2   | Python-side dedup on `(program_id, session_id, cmd_ts)` before upsert; distinct rejected reason.                 | T-04, T-09 |
| C-3   | Write full `rows[]` field list into `api.md#ingest-files-api` (blocking write).                                  | T-16 |
| C-4   | Auth wiring mirrors `manifest.py` — manual `await get_ingest_token(...)`, fresh `HTTPBearer` instance.           | T-05 |
| C-5   | Delete `app/api/ingest.py`; delete `app/schemas/activity.py` orphan; update `pydantic-patterns` SKILL.md.        | T-06 |
| C-6   | Envelope `kind` gets one owning module shared with ING-03.                                                       | T-02, T-10 |
| C-7   | Fixed field allowlist on `ingest_write_completed`; rejection reasons carry row index + reason code only.         | T-04, T-11 |
| C-8   | p95 NFR re-indexed to accumulated table size (up to 160k rows) AND batch size — stated in NFR (PRD).             | T-15 |
| C-9   | `rebuild_org_rollups()` REMOVED from the request path; out-of-band mechanism pinned in planning.                 | D-01, ADR-0012, T-04, T-05 |
| C-10  | Perf test seeds pre-populated `usage_events` table (20k / 40k / 160k rows) BEFORE 5000-row push.                 | T-15 |
| C-11  | Correct `data.md#rollup-rebuild` `invariant:` text.                                                              | T-17 |

### Cross-Feature Dependency Notes

- **ING-04 (MCP push_activity / push_artifacts)** consumes `ingest-files-api` — the T-16 write of the full `rows[]` field list is a blocking prerequisite for ING-04's own PLAN.
- **ING-06 (manual CLI ingester)** consumes `ingest-files-api` — same blocking dependency on T-16.
- **ING-09 (scheduled ingestion cron)** consumes `ingest-files-api` — same blocking dependency on T-16.
- **ING-03 (artifacts ingest)** shares `services/api/app/core/ingest_kind.py` (D-03). ING-03 extends the `_ACCEPTED_KINDS` frozenset with `"artifacts"` in its own scope — this story ships `{"activity"}`.

### Carry-forward — NOT this story's to fix

Recorded here per PRD Scope § Out; no task addresses these.

- `docs/config/stack-smoke.md` port mismatch (5432 vs dev container 5442). Owner: infra.
- ING-04's ACs read `files:`/`artifacts:` from `profile.yaml` but ING-10 moved both to `program.yaml`. Owner: ING-04.
- `ingest_tokens.last_used_at` never updated (research R-13). Owner: ING-01.

## 7. Test Strategy

Test-case ids are from `docs/test-cases/ING-02.json` (tracker #293, #294). The 3 gap items dispositioned to plan-implementation by the operator hard-cap (test-case count = 2) are added here as explicit test tasks.

| Layer | Test path | Type | TCs / ACs / gaps covered | Task | Notes |
|-------|-----------|------|--------------------------|------|-------|
| Unit | `services/api/tests/unit/test_activity_ingest_alias_mapper.py` | unit | FR-4 (wire→column alias mapping); gap #1 | T-07 | Reads `_ROW_SCHEMA_COLUMN_MAP` from `app/services/activity_ingest.py`; asserts the 5 aliases (per Q-01) resolve correctly and unknown fields on a row are silently dropped, row still commits. |
| Unit | `services/api/tests/unit/test_activity_ingest_chunk_ceiling.py` | unit | FR-2 / C-1 (bind-parameter ceiling) | T-08 | Asserts `len(UsageEvent.__table__.columns) * _MAX_ROWS_PER_INSERT ≤ 65_500` — the ceiling, not the specific integer, so a future column addition trips it. |
| Unit | `services/api/tests/unit/test_activity_ingest_intra_batch_dedup.py` | unit | FR-3 / C-2 (last-wins dedup, `intra_batch_duplicate` reason) | T-09 | Feeds a hand-built row list with a duplicate on `(program_id, session_id, cmd_ts)`; asserts the last row survives, dropped row lands in `rejected[]` with reason `intra_batch_duplicate` and index of the dropped row. |
| Unit | `services/api/tests/unit/test_ingest_kind.py` | unit | FR-7 (envelope kind allowlist) | T-10 | Asserts `accept_envelope_kind("activity") is True`, `accept_envelope_kind("artifacts") is False` (until ING-03 lands), `accept_envelope_kind("") is False`. |
| Unit | `services/api/tests/unit/test_ingest_files_pii_logging.py` | unit | C-7 / FR-8 (ingest_write_completed allowlist; rejection index-only) | T-11 | Mirrors `services/api/tests/unit/test_manifest_pii_logging.py::_EXPECTED_KEY_SET` shape — captures emitted records, asserts key set equals the allowlist exactly, asserts no rejection entry carries row content. |
| Unit | `services/api/tests/unit/test_ingest_files_route_registered.py` | unit | FR-6 (boot smoke — `/api/ingest/files` mounted); gap #2 | T-12 | Follows the `test_auth_oidc_login.py:184` / `test_auth_logout.py:199` precedent: `assert any(getattr(route, "path", None) == "/api/ingest/files" for route in create_app().routes)`. Chosen over a `services/api/tests/smoke/` new-directory approach because no smoke dir exists today and this codebase's existing convention for the same assertion lives under `tests/unit/`. |
| Unit (integration-style) | `services/api/tests/unit/test_ingest_files_idempotency.py` | integration | ING-02-TC-01 (#293) → AC-1, AC-4-envelope, AC-5-dedup-reason, AC-6, FR-1, FR-2, FR-3, FR-7, FR-8 | T-13 | Full happy-path test per the JSON test case. Lives under `tests/unit/` matching this codebase's convention for real-Postgres integration tests (no `tests/integration/` dir per `docs/config/project-commands.yaml`; BED-05 established the same convention with `test_rollup_rebuild_concurrency.py`). |
| Unit (integration-style) | `services/api/tests/unit/test_ingest_files_auth_denial.py` | integration | ING-02-TC-02 (#294) → AC-2, AC-3, AC-4-413, AC-4-envelope-kind, AC-5 enumeration, FR-5, FR-7, C-7 | T-14 | Full denial matrix per the JSON test case. Same location rationale as T-13. |
| Perf | `services/api/tests/perf/test_ingest_files_perf.py` | performance | NFR-performance (C-8, C-10); gap #3 | T-15 | Seeds `usage_events` to 20k / 40k / 160k rows across ≥ 3 programs; measures the 5000-row push p95; module docstring records the seeded sizes + per-size p95 budgets per Research Rec #1. Reuses the pytest-based perf convention BED-05 established in `tests/perf/test_rollup_rebuild_perf.py` — no new runner install. |

### Runner setup

Pytest is the declared unit + perf runner (`docs/config/project-commands.yaml` `test:`, `test_unit:`). `services/api/tests/perf/` is already established by BED-02/BED-03/BED-05 (`test_range_pagination_perf.py`, `test_rollup_rebuild_perf.py`). T-15 adds a new file under it — no new runner install, config, or task required.

## Plan validation

- Date: 2026-09-11
- Verdict: PASS
- Wiring:               PASS  (F-01 ← F-08; F-02 ← F-01; F-03 ← F-01, F-02; F-04 ← F-01; F-05 self-registers via `down_revision`; F-06 model change consumed by F-02 + F-07 schema-diff gate; all test files are leaves per the wiring exception)
- Docs:                 PASS  (T2 fires — new HTTP route `POST /api/ingest/files`; T-16 updates `docs/requirements/api.md#ingest-files-api` and T-18 updates BOTH the root `README.md` API table AND `services/api/README.md`; T1/T3/T4 do not fire — no new runnable surface, no new env var per D-03 precedent, no new service or port)
- Runner-setup:         PASS  (pytest already installed and configured for unit + perf; `tests/perf/` established by BED-05 F-08; T-15 adds a new file, no new runner setup)
- Cross-section:        PASS  (DAG acyclic — verified by hand; every test-strategy type has ≥1 backing task; every F-NN referenced by ≥1 task's `files[]`; every task `files[]` id resolves in `file_plan`; no two DAG-independent tasks write the same file — verified by hand)
- Config drift:         PASS  (C1 — no new runtime dep; SQLAlchemy `pg_insert` already imported by `manifest_ingest.py`. C2 — no new service dir. C3 — no new port or `*_PORT`/`*_HOST` env var; the FastAPI `BackgroundTasks` mechanism per D-01 is a built-in FastAPI seam, not a new service)
- Decision-promotion:   PASS  (D-01 blast:system → adr:ADR-0012 ✓; D-02 blast:feature rev:mechanical → adr:— per rule, no promotion required; D-03 blast:service rev:mechanical → adr:— per rule, no promotion required)
- Rounds:               1
