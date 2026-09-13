# Code Review — ING-02 (`POST /api/ingest/files` — activity ingest)

- Date: 2026-09-12
- Mode: story (GATE MODE — report-only; dispatched by `/arh-implement` Step 2 Validate ∥ Review gate)
- Source snapshot anchor: SHA1 `0b37fd7ac6cf7796d451ec835151705e2a2e57a1`
- Files reviewed: 25 (12 added, 11 modified, 2 deleted)
- Verdict: **PASS WITH WARNINGS**

## Executive summary

Implementation faithfully executes PRD + PLAN with two exceptions worth flagging. ADR-0012 boundary is honoured strictly: `rebuild_org_rollups` is unreachable from the request path — the service imports it only inside `dispatch_org_rebuild`, and the router only ever passes `lambda: background_tasks.add_task(dispatch_org_rebuild)` to the service. FR-8 / C-7 PII discipline is real: `log_ingest_write_completed` is keyword-only against a fixed allowlist, `_LOG_FIELD_ALLOWLIST` is snapshot-asserted by T-11, `RejectionEntry` schema forbids row content, and `_classify_row_error` inspects `type`/`loc`/`msg` only (never `input`/`ctx`). Router order matches PLAN.md T-05 and api.md verbatim (JSON parse → dict → `program_id` → envelope-kind → auth → 413). Migration 006 is additive-nullable, index-free, safe on a non-empty prod table; column count 24 pins `_MAX_ROWS_PER_INSERT = 2_730` and T-08 asserts the ceiling from `__table__.columns` at runtime.

🟢 strengths: ADR-0012 seam is airtight (`dispatch_org_rebuild` opens its own `SessionLocal`; router never touches `rebuild_org_rollups`); PII allowlist is enforced by shape (keyword-only signature + module frozenset + T-11 diff); T-06 stub cleanup landed atomically with SKILL.md retarget; contract updates in `api.md` and `data.md#rollup-rebuild` shipped with the code.

⚠️ warnings: NFR-performance p95 3.67–3.98 s at 20k/40k/160k vs 3.0 s budget on local dev — accepted per D-04 (carry-forward to CI provisioning); intra-batch dedup shipped inline vs the `_dedup_intra_batch()` helper PLAN.md § 2 F-02 sketched (plan-drift accepted, integration coverage exists); service claims defence-in-depth on `_ENVELOPE_ROW_CAP` in api.md but the constant is documentation-only in `activity_ingest.py`; three test files renamed from PLAN's declared paths.

🛑 blockers: none.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|-------------------------------------------------------------------|
| CRITICAL |   0   | — |
| HIGH     |   1   | performance (1) |
| MEDIUM   |   2   | design-patterns (1), contract-drift (1) |
| LOW      |   4   | plan-drift (2), scope-creep (1), documentation (1) |

## Detailed findings

### HIGH

#### F-1 — performance: NFR p95 ≤ 3 s not met at 20k/40k/160k (accepted per D-04)
- Category: safety/performance (integration points)
- Path: `services/api/tests/perf/test_ingest_files_perf.py:280` + `services/api/pyproject.toml:56-59`
- Source: `docs/features/ING-02/REQUIREMENTS.md` § Non-functional requirements C-8, C-10; `FLAGS.md` AF-05; `DECISIONS.md` D-04
- Description: T-15 measured 3.673 s / 3.680 s / 3.982 s at 20k / 40k / 160k accumulated `usage_events` rows against the 3.0 s budget. Root cause per T-15 diagnosis is on-path residual (per-row Pydantic validate + pre-read + chunked upsert + `rebuild_program_rollups` at 10k in-program) on local dev (macOS + non-CI-tuned Postgres), NOT an ADR-0012 leak — org rebuild is correctly monkey-patched off the request path inside the timed window, and the ~8% growth 20k→160k confirms BED-05 D-01's in-program bound holds. Accepted via D-04 (`@pytest.mark.perf` + `addopts = "-m 'not perf'"`) so the failing signal is preserved for `pytest -m perf` runs without red-ing default local runs. Do not downgrade — flagged as HIGH per the source directive.
- Suggested fix: none in-scope for ING-02; carry-forward to CI provisioning per D-04 § "Follow-up (carry-forward): once CI is provisioned, re-enable perf tests in the default CI matrix. Re-evaluate whether the 3.0 s budget or the on-path chain needs the fix — decide on measured CI evidence, not local dev." Review-agent agrees with the D-04 disposition.

### MEDIUM

#### F-2 — design-patterns: intra-batch dedup shipped inline instead of the `_dedup_intra_batch()` helper PLAN.md sketched
- Category: design-patterns (plan-drift)
- Path: `services/api/app/services/activity_ingest.py:181-196` (the inline dedup block)
- Source: `docs/features/ING-02/PLAN.md` § 2 F-02 (declared `_dedup_intra_batch(valid_rows) -> (dedup_rows, dedup_rejected)` helper); `FLAGS.md` AF-03
- Description: PLAN.md § 2 F-02 declares `_dedup_intra_batch` as a named private helper. Shipped code inlines the same logic inside `ingest_files()` (≤15 lines). Semantically identical: forward iteration, last-wins overwrite of the `(program_id, session_id, cmd_ts)` map, dropped indices land in `rejected[]` with reason `intra_batch_duplicate`. Testability consequence per AF-03: T-09 could not import dedup as a callable and drives `ingest_files()` end-to-end with a fake `AsyncSession`; the composite-key "different `program_id` → distinct rows" case cannot be positively exercised via `ingest_files()` because the scope filter rejects mismatches (as `program_id_mismatch`) BEFORE dedup runs — verified in `test_ingest_intra_batch_dedup.py::test_different_program_id_is_not_a_duplicate`, which observes the mismatch classification, not a merge. Behaviour is correct; only helper-shape and unit-callability drift.
- Suggested fix: accept — inline dedup is idiomatic and integration tests T-13/T-14 cover the DB side. Refactor to helper only if a future story needs to call dedup outside `ingest_files()`. Agrees with AF-03 triage-accept.

#### F-3 — contract-drift: api.md claims `activity_ingest._ENVELOPE_ROW_CAP` enforces the row cap defence-in-depth; the service does not re-check it
- Category: contract-drift
- Path: `docs/requirements/api.md:281` (`activity_ingest._ENVELOPE_ROW_CAP = 5_000 in the service enforces the same limit defence-in-depth`) vs `services/api/app/services/activity_ingest.py:83-86` (`the service never re-checks it`)
- Source: `docs/requirements/api.md#ingest-files-api` limits clause
- Description: `api.md#ingest-files-api` limits: line advertises `_ENVELOPE_ROW_CAP` in the service as active defence-in-depth. The shipped constant in `activity_ingest.py` is present but the module comment openly states "the service never re-checks it". Router-tier enforcement is real, but the two-tier "router + service" claim in the contract is over-stated. Also relevant: because the router's 413 check is `isinstance(raw_rows, list) and len(raw_rows) > _ENVELOPE_ROW_CAP`, a non-list `rows` (e.g. a very long string) bypasses both the 413 and any service-tier cap, then gets iterated in `for index, raw_row in enumerate(raw_rows)` — post-auth DoS surface bounded only by ASGI body-size limits.
- Suggested fix: either (a) add `if len(raw_rows) > _ENVELOPE_ROW_CAP: raise` in `activity_ingest.ingest_files()` to make the claim true and close the non-list DoS surface, or (b) reword `api.md#ingest-files-api` limits to "the constant is documentation-only; the router is sole enforcer" and rely on ASGI body-size limits for non-list shapes. Prefer (a) — matches `.claude/rules/security-baseline.md` "Validate untrusted input at trust boundaries".

### LOW

#### F-4 — plan-drift: three test files renamed from tasks.json `file_plan` declared paths
- Category: scope-creep / plan-drift
- Path: `services/api/tests/unit/test_ingest_bind_param_ceiling.py` (planned `test_activity_ingest_chunk_ceiling.py`, F-12); `services/api/tests/unit/test_ingest_intra_batch_dedup.py` (planned `test_activity_ingest_intra_batch_dedup.py`, F-13); `services/api/tests/unit/test_ingest_write_completed_pii.py` (planned `test_ingest_files_pii_logging.py`, F-16)
- Source: `docs/features/ING-02/tasks.json` `file_plan` F-12 / F-13 / F-16
- Description: Three test files land at names that differ from `tasks.json`'s declared `file_plan` paths. Coverage matches the planned scope; behaviour unchanged. Scope-creep skill checks per-task `files[]` against declared paths — technical drift.
- Suggested fix: accept — file-name choice is a mechanical rename with equivalent semantics; update `tasks.json` `file_plan` paths in the next housekeeping pass or leave as historical record. No behavioural fix needed.

#### F-5 — scope-creep: `services/api/pyproject.toml` edit not in any task's `files[]`
- Category: scope-creep
- Path: `services/api/pyproject.toml:56-59` (pytest markers + `addopts`)
- Source: `docs/features/ING-02/tasks.json` `file_plan` (no F-NN entry for `pyproject.toml`)
- Description: The `[tool.pytest.ini_options]` marker + `addopts` amendment (per D-04) touches a file not in `file_plan`. Authorised by D-04, which recorded the amendment to PLAN.md § 7 "no new runner setup" — legitimate escalation via the decision log, not a silent edit. Flagged for completeness; not a violation given D-04.
- Suggested fix: none — accept per D-04.

#### F-6 — documentation: `ingest_files.py` module docstring cites "FR-6 structural isolation" for the `_http_bearer` line, should be FR-5 / C-4
- Category: documentation (comments)
- Path: `services/api/app/api/ingest_files.py:24` (`ingest_auth.py`'s own instance is private and never imported (FR-6 structural isolation)`)
- Source: `docs/features/ING-02/REQUIREMENTS.md` FR-5 (auth wiring — mirror `manifest.py`, fresh `HTTPBearer(auto_error=False)`, never import `_http_bearer`)
- Description: The rule that private `_http_bearer` must not be imported is FR-5 / C-4 (auth-wiring shape), not FR-6 (stub cleanup + orphan handling). One-token mislabel in the docstring narrative — no behavioural impact; the surrounding rationale is correct.
- Suggested fix: change `(FR-6 structural isolation)` → `(FR-5 / C-4)` in the module docstring on next touch. Not a blocker.

#### F-7 — documentation: `services/api/README.md` "Ingest token auth" section still leads with "No route declares `Depends(get_ingest_token)` yet"
- Category: documentation
- Path: `services/api/README.md:104-108` (ingest-token auth § "No route declares Depends(get_ingest_token) yet — this story ships the dependency only" followed by an ING-02 consumer line)
- Source: `FLAGS.md` AF-04
- Description: Literal statement stays true (both `/manifest` and `/files` call `get_ingest_token` manually, not via `Depends()`), but the "this story ships the dependency only" wording pre-dates ING-10 and ING-02 both being live consumers. T-18 added a follow-up sentence naming ING-02 rather than rewriting the drift, per `.claude/rules/surgical-changes.md`. Agrees with AF-04 triage-accept: dependency-centric section, route documentation lives in the root README API table.
- Suggested fix: accept — enumerate consumers during a future ingest-docs consolidation.

## Open flag re-assessment

| Flag | Triage | Review agrees? | Note |
|---|---|---|---|
| AF-01 (T-17 invariant vs commit_boundary_note scope mismatch) | open | agree — accept | Invariant field preserved verbatim per 2026-09-04 do-not-rewrite-contract-field-text precedent; footnote + `implementation_owner_note` carry the correction. No new finding. |
| AF-02 (envelope-invalid HTTP status — 400 shipped) | triaged-accept | agree — accept | 400 matches PLAN.md T-05 (`accept_envelope_kind (400 if reject — FR-7 / AC-4 tier)`), REQUIREMENTS.md FR-7, and `api.md#ingest-files-api` errors block. Manifest.py precedent. No finding. |
| AF-03 (dedup shipped inline vs `_dedup_intra_batch` helper) | open | agree — accept | Recorded as F-2 above (MEDIUM, plan-drift accepted). Integration T-13/T-14 covers the DB side; the "different `program_id` → distinct rows" case is unreachable through `ingest_files()` because scope filter runs first and is verified via `program_id_mismatch` classification, not merge. |
| AF-04 (README ingest-token-dep wording drift) | open | agree — accept | Recorded as F-7 above (LOW). Carry-forward to future ingest-docs consolidation. |
| AF-05 (NFR p95 3.67–3.98 s vs 3.0 s on local dev) | triaged-accept-(c) per D-04 | agree — accept per D-04 | Recorded as F-1 above (HIGH — severity not downgraded per source directive). Perf test correctly monkey-patches `dispatch_org_rebuild` inside the timed window so ADR-0012 boundary is honoured in the measurement. Carry-forward to CI provisioning. |

## Six-dimension summary

1. **Module structure & boundaries** — PASS. Clean separation: router (`ingest_files.py`) is envelope-tier only (parse + envelope + auth + 413), service (`activity_ingest.py`) is validation + dedup + upsert + program rebuild + org dispatch. `ingest_kind.py` owns the envelope vocabulary as a shared module for ING-03 to extend (D-03). Schema module (`ingest_files.py`) has no view of the envelope.
2. **Design patterns** — PASS with F-2 warning (dedup helper drift). Everything else matches the manifest.py precedent verbatim: manual `await get_ingest_token(...)`, fresh private `_http_bearer = HTTPBearer(auto_error=False)`, raw JSON body then per-row Pydantic, `_ROW_SCHEMA_COLUMN_MAP` alias table alongside `Field(alias=...)`.
3. **Component / module architecture** — PASS. `on_org_rebuild: Callable[[], None]` injected by router so `activity_ingest` never references `BackgroundTasks` or `SessionLocal` on the request path (dependency direction inbound only). `dispatch_org_rebuild` opens its own `SessionLocal` inside the module and swallows exceptions per ADR-0012.
4. **Integration points** — PASS with F-1 warning (NFR budget). Error envelope 400/401/403/404/413 matches `api.md`; `pg_insert(...).on_conflict_do_update()` uses `_CONFLICT_UPDATE_COLUMNS` derived from `__table__.columns` at import time (auto-picks up column additions); one transaction per batch; commit precedes program rebuild; org dispatch happens after the response envelope is fully materialised.
5. **Testability** — PASS. Nine test files cover FR-2 ceiling, FR-3 dedup vocabulary, FR-4 alias mapping + unknown-field drop, FR-6 route registration + old-stub-absent, FR-7 kind allowlist, FR-8 log + response PII discipline, AC-1/6 idempotency, AC-2/3/4/5 auth-denial matrix, and NFR performance. T-11 and T-13 both use the same `_RecordCapturingHandler` idiom that works around `migrations/env.py:19`'s `fileConfig(disable_existing_loggers=True)` trap — good.
6. **Safety & security** — PASS with F-3 warning (defence-in-depth gap on non-list `rows`). PII allowlist enforced by shape (keyword-only signature); `RejectionEntry` schema is `{index, reason}`-only; `_classify_row_error` never reads `input`/`ctx`; timestamp validator raises `ValueError("malformed_iso_date")` without interpolating the value; `_LOG_FIELD_ALLOWLIST` and `_FR8_ALLOWLIST_LITERAL` snapshot each other so drift is caught on either side; migration 006 is additive-nullable (Postgres 11+ catalog-only, zero-lock).

## ADR-0012 compliance check

Ran the explicit check the source directive called out: no `rebuild_org_rollups` call in the router or service request path outside a `BackgroundTasks` seam.

- `services/api/app/api/ingest_files.py` — does not import `rebuild_org_rollups`; `dispatch_org_rebuild` reference is only inside `lambda: background_tasks.add_task(dispatch_org_rebuild)` (line 154). ✓
- `services/api/app/services/activity_ingest.py` — imports `rebuild_org_rollups` from `app.services.rollup_rebuild` (line 62) but the only call site is `await rebuild_org_rollups(session)` inside `async def dispatch_org_rebuild()` (line 293), which is the caller-supplied hook target. `ingest_files()` never references `rebuild_org_rollups` — only `on_org_rebuild()` (the injected callable). ✓
- `dispatch_org_rebuild()` opens a fresh `SessionLocal()` and swallows exceptions with a PII-free `logger.exception("ingest_org_rollup_task_failed")` — matches ADR-0012 § Consequences exactly. ✓
- Perf test T-15 monkey-patches `ingest_files_module.dispatch_org_rebuild` to a no-op so the measured window models the ADR faithfully. ✓

Verdict: ADR-0012 honoured.

## Contract-drift check

Story produces `ingest-files-api` (`docs/requirements/api.md`) and updates `rollup-rebuild.commit_boundary_note` (`docs/requirements/data.md`).

- `api.md#ingest-files-api` — full shape written per C-3: endpoint, auth, request body, limits, rows shape (schema module, wire aliases, fields, unknown-field policy, idempotency, intra-batch dedup), response shape, rejection vocabulary, `rollup_summaries_scope`, errors, observability. Matches shipped code. One drift recorded as F-3 (defence-in-depth claim vs shipped comment).
- `data.md#rollup-rebuild.commit_boundary_note` — updated to reflect ADR-0012 caller-side ordering (commit `usage_events` → sync `rebuild_program_rollups` → dispatch `rebuild_org_rollups` via `BackgroundTasks`). Superseding-decisions footnote added. Invariant text preserved verbatim per precedent (AF-01 accepted).

Verdict: no unresolved contract-drift.

## Scope-creep check

Files touched vs `tasks.json` `file_plan`:

- All 15 `create` entries land at declared paths, except three test files renamed (F-4, LOW).
- All 7 `modify` entries land at declared paths.
- Both `delete` entries (`app/api/ingest.py`, `app/schemas/activity.py`) executed.
- `services/api/pyproject.toml` edit (F-5) not in `file_plan` but authorised by D-04 § "narrowly amends PLAN.md § 7".

Verdict: no unauthorised scope-creep.

## What went well

- ADR-0012 seam is airtight from three angles (router never imports `rebuild_org_rollups`; service isolates the call to `dispatch_org_rebuild` alone; perf test elides the task body inside the timed window).
- PII discipline enforced by shape, not by convention: keyword-only signature on `log_ingest_write_completed`, module frozenset `_LOG_FIELD_ALLOWLIST`, T-11 snapshot pin against `_FR8_ALLOWLIST_LITERAL`, `RejectionEntry` schema fields locked to `{index, reason}`, `_classify_row_error` inspects `type`/`loc`/`msg` only.
- Chunk-ceiling test asserts `len(UsageEvent.__table__.columns) * _MAX_ROWS_PER_INSERT < 65_535` from live model metadata — a future column addition trips the test instead of overflowing Postgres.
- T-06 atomic stub cleanup (delete `app/api/ingest.py` + `app/schemas/activity.py` + SKILL.md retarget + router register in `app/main.py`) landed together, closing BED-05 R-09 and research R-10 carry-forwards in one PR.
- Envelope-kind-before-auth ordering is directly asserted (`test_envelope_kind_check_runs_before_auth`) so a future refactor that flips the order is caught by the suite.

## Recommendation

**PASS WITH WARNINGS.** Zero CRITICAL, one HIGH (F-1, accepted per D-04 with carry-forward to CI provisioning), two MEDIUM (F-2 accepted plan-drift; F-3 contract-drift on `_ENVELOPE_ROW_CAP` defence-in-depth claim — consider closing in a follow-up), four LOW. All five open flags AF-01..AF-05 read as their triage records; no upgrades. ADR-0012 honoured; contract-drift resolved; scope-creep bounded and authorised. Proceed to `/arh-security-review` after the Validate ∥ Review gate join.
