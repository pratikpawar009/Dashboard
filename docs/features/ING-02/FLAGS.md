# ING-02 — session flags

### AF-01: T-17 F-22 invariant vs commit_boundary_note scope mismatch
- kind: risky-pattern
- task: T-17
- source: docs/features/ING-02/PLAN.md § 2 F-22 vs § 6 C-11
- summary: PLAN.md F-22 mentions BOTH the O(events) invariant clause correction AND the commit_boundary_note update; C-11 in Conditions cites only invariant correction. T-17 shipped commit_boundary_note update and added a superseding-decisions footnote linking ADR-0012. The invariant field text was preserved verbatim per the 2026-09-04 "do-not-rewrite-the-contract-field-text" precedent; the existing `implementation_owner_note` and the new footnote together carry the cost-model correction. Recommend triage decision: (a) accept — footnote-level correction is sufficient because the invariant field is frozen per precedent; or (b) explicit invariant edit in a follow-up. Not a blocker for ING-02 implementation.
- status: triaged-accept-reviewer

### AF-02: T-16 API contract HTTP status for envelope-invalid — 400 shipped (not 422)
- kind: risky-pattern
- task: T-16
- source: docs/features/ING-02/PLAN.md § 2 T-05 vs orchestrator T-16 dispatcher
- summary: Orchestrator's T-16 dispatch listed "422 (envelope invalid)". PLAN.md T-05 pins envelope-kind rejection at 400 (`accept_envelope_kind (400 if reject — FR-7 / AC-4 tier)`); REQUIREMENTS.md FR-7 says "AC-4 abort tier — 400 or 413-tier reject-all". T-16 correctly shipped 400 per PLAN.md and manifest.py precedent. Orchestrator ruling: accept 400. No follow-up required.
- status: triaged-accept

### AF-03: T-04 buried intra-batch dedup inline instead of the `_dedup_intra_batch` helper
- kind: plan-drift
- task: T-09 (raised by), T-04 (shipped)
- source: services/api/app/services/activity_ingest.py:146-158 (inline block) vs docs/features/ING-02/PLAN.md § 2 F-02 (`_dedup_intra_batch(valid_rows) -> (dedup_rows, dedup_rejected)` helper)
- summary: Semantically identical, ≤15 lines. Two testability consequences: (1) T-09 could not import dedup as a callable — used monkeypatched fake AsyncSession end-to-end. (2) The composite-key spec "different program_id → distinct rows" cannot be positively tested via `ingest_files()` since scope filter rejects mismatches before dedup runs. Not blocking; integration tests T-13/T-14 cover the DB side. Recommend triage decision: (a) accept — inline dedup is idiomatic; refactor deferred to a future story; or (b) refactor to helper in fix-loop.
- status: triaged-accept-reviewer

### AF-04: services/api/README.md ingest-token-dep section wording drift (carry-forward)
- kind: doc-drift
- task: T-18 (raised); pre-existing from ING-01 → ING-10 → ING-02
- source: services/api/README.md:104 § Ingest token auth section
- summary: Section still says "No route declares Depends(get_ingest_token) yet — this story ships the dependency only". ING-10 (manifest) manually calls the dep; ING-02 now does too. T-18 added a follow-up sentence naming ING-02 as consumer but did not rewrite the drift, per surgical-changes. Recommend triage decision: (a) accept — dependency-centric section, route documentation lives in root README API table; or (b) enumerate consumers during a future ingest-docs consolidation.
- status: triaged-accept-reviewer

### AF-05: [HIGH] ING-02 NFR-performance ≤3s p95 not met on local dev — 3.67-3.98s vs 3.0s budget
- kind: nfr-miss
- task: T-15 (measured), all shipped ING-02 code
- source: services/api/tests/perf/test_ingest_files_perf.py:280 + T-15 result payload
- summary: The perf test was written correctly and runs the exact NFR contract (5000-row push at 20k/40k/160k accumulated rows, ADR-0012 org rebuild monkey-patched to no-op inside the timed window so the measurement is REQUEST-path only). Measured latencies: 20k=3.673s, 40k=3.680s, 160k=3.982s vs 3.0s budget. Root-cause diagnosis (from T-15 agent):
  - NOT ADR-0012 leak — org rebuild is correctly off the request path.
  - NOT table-size-dependent — only ~8% growth 20k→160k confirms BED-05 D-01's in-program-bound claim.
  - The ~3.7s floor is on-path residual: validate 5000 rows (Pydantic per-row) + pre-read 5000 keys (SELECT-then-INSERT-or-UPDATE) + chunked upsert (2 chunks × 2730 rows) + rebuild_program_rollups at 10k in-program.
  - Local dev = macOS host + non-CI-tuned Postgres. CI baseline unknown.
- possible paths (decision required):
  (a) **Optimize on-path chain** — profile, cut where possible (Pydantic validate_python skip, bulk pre-read, etc.). Cost: 1-2 days engineering, may not hit 3.0s if it's fundamentally the pre-read cost.
  (b) **Re-baseline NFR against measured evidence** — REQUIREMENTS.md § NFR-performance updated with new p95 target (e.g. ≤4.5s at 160k on local; ≤3.0s on CI-tuned hardware). Requires a small PRD amendment + user approval.
  (c) **Mark perf test @pytest.mark.perf + exclude from default run** — treat as advisory. Contradicts PLAN.md § 7 "no new runner setup" and hides a real NFR miss from the evidence pass. Not recommended.
  (d) **Measure on CI-representative hardware first** — the 3.7s could be macOS/dev-Postgres overhead. If CI Postgres hits 3.0s, keep NFR as-is.
- blocks: Step 1 evidence pass will fail on the runtime dimension IF the perf test runs by default. It does — no marker, no exclusion.
- status: triaged-accept-(c) — per D-04; carry-forward to CI provisioning
