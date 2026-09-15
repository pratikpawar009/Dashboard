---
feature_id: ING-04
story_id: ING-04
target_ref: feature/ING-04 (working tree vs main)
mode: story · GATE MODE — report-only · ROUND 2
reviewer: code-review-agent
date: 2026-09-14
snapshot_hash: dd7536287d525e90c8f701e34cd0591d441aa49ef72a759c318d81a72c1b3b12
round_1_verdict: BLOCKED (5 HIGH)
round_2_verdict: PASS WITH WARNINGS (0 HIGH · 2 MEDIUM new · 3 MEDIUM/LOW carry-forward)
---

# Code Review — ING-04 (ROUND 2, post fix-pass)

- Verdict: **PASS WITH WARNINGS**
- Closures verified: F-1 ✓ · F-2 ✓ · F-3 ✓ · F-4 ✓ · F-5 ✓
- New findings this round: F-9 (MEDIUM), F-10 (MEDIUM)
- Carry-forward from round 1: F-6 (MEDIUM), F-7 (LOW), F-8 (LOW)

## Executive summary

Every HIGH finding from round 1 is closed at the code + produced-contract level:
`push_activity` now reads the real `IngestFilesResponse` shape (F-1), both tool
signatures + `@server.tool()` wrappers restore `program_id: str | None = None`
with `program_id or program.program_id` precedence (F-2), the success envelope
is the FR-2 shape verbatim (F-3), 401/403 branch to `unauthorized`/`forbidden`
before the generic 5xx path with the full FR-5 aggregate fields (F-4), and the
missing-token envelope is the FR-6 code+message form (F-5). The
`docs/requirements/api.md#mcp-tools` contract block was updated to describe
the same shapes the code returns, so ING-05 will bind to the PRD-aligned
surface. Regression sweep is clean on architecture, security (R-06/R-07 still
intact end-to-end), reliability (retry / timeout / no-4xx-retry unchanged),
and pattern adherence.

Two MEDIUM regressions surfaced during the sweep. Five `.py.new` files were
left uncommitted in `services/mcp-server/tests/unit/` — they contain the
intended stronger assertions (full FR-5 envelope + a 403-forbidden branch
case) but were never promoted to replace the originals (F-9). The consequence
is a test-coverage gap on the very envelope F-4 was meant to close: the
`.py` tests still only assert `success`, `error`, `http_status`, and call
count — a future refactor could regress the FR-5 aggregate fields without
any test failing, and no test currently exercises the 403 code path (F-10).
Neither re-opens F-4 (the code path satisfies FR-5) but both should ride as
tightening work before merge.

Per the gate rule (no CRITICAL, no HIGH, MEDIUM/LOW only) → **PASS WITH
WARNINGS**.

🟢 strengths: five round-1 HIGH findings correctly closed at code + contract; regression sweep clean
⚠️ warnings: 2 MEDIUM (stray `.py.new` files, FR-5-envelope coverage gap + missing 403 test)
🟡 carry-forward: F-6 sync/async, F-7 story-header edit, F-8 activity.jsonl auto-append

## Findings summary

| Severity | Count | Category distribution                                              |
|----------|-------|---------------------------------------------------------------------|
| CRITICAL |   0   | —                                                                   |
| HIGH     |   0   | —                                                                   |
| MEDIUM   |   3   | scope-creep (1), testability (1), design-patterns (1 carry-forward) |
| LOW      |   2   | scope-creep (2 carry-forward)                                       |

## Closure verification — F-1..F-5

### F-1 — CLOSED (correctness / contract-drift)

- **Path**: [services/mcp-server/src/agentrise_mcp/tools/push_activity.py](services/mcp-server/src/agentrise_mcp/tools/push_activity.py#L220-L232)
- **Evidence**: `body.get("inserted", 0)` + `body.get("updated", 0)` are summed into `inserted_total` / `updated_total`; `body.get("rejected") or []` is extended into `rejected`; `body.get("rollup_summaries") or {}` is merged into `rollups` with last-write-wins on collision. All four keys match `IngestFilesResponse` in [services/api/app/schemas/ingest_files.py](services/api/app/schemas/ingest_files.py#L151-L182) exactly. The stale keys (`rows_received`, `rows_upserted`, `rejections`) no longer appear on any read path in `push_activity`.
- **Test evidence**: [test_push_activity.py](services/mcp-server/tests/unit/test_push_activity.py#L47-L58) `_backend_ok()` fixture builds the real `IngestFilesResponse` shape (`received`, `valid`, `inserted`, `updated`, `rejected`, `rollup_summaries`) — masking of the drift removed.

### F-2 — CLOSED (contract-drift)

- **Path**: [services/mcp-server/src/agentrise_mcp/tools/push_activity.py](services/mcp-server/src/agentrise_mcp/tools/push_activity.py#L58-L61), [services/mcp-server/src/agentrise_mcp/tools/push_artifacts.py](services/mcp-server/src/agentrise_mcp/tools/push_artifacts.py#L94-L97), [services/mcp-server/src/agentrise_mcp/server.py](services/mcp-server/src/agentrise_mcp/server.py#L40-L57)
- **Evidence**: Both tool bodies now take `program_id: str | None = None, workspace_root: str | None = None`. `effective_program_id = program_id or program.program_id` implements FR-1 override semantics. `server.py` `@server.tool()` wrappers pass both args through unmodified.
- **Contract evidence**: [docs/requirements/api.md#mcp-tools](docs/requirements/api.md) now documents `push_activity(program_id: str | None = None, workspace_root: str | None = None) -> dict` and analogously for `push_artifacts`. Contract is aligned FORWARD to the PRD, not backward to a partial impl — the round-1 concern about contract drift in the OTHER direction is resolved.

### F-3 — CLOSED (correctness / FR-2)

- **Path**: [services/mcp-server/src/agentrise_mcp/tools/push_activity.py](services/mcp-server/src/agentrise_mcp/tools/push_activity.py#L263-L272)
- **Evidence**: Success return is `{success, files_read, rows_read, batches, inserted, updated, rejected, rollups}` — the FR-2 shape verbatim. `files_read` is incremented per matched file, `rows_read = len(rows) + len(rejected)` (attempted parses), `batches` supplies the count formerly named `batches_sent`, `rollups` supplies the aggregated `rollup_summaries`.
- **Test evidence**: [test_push_activity.py](services/mcp-server/tests/unit/test_push_activity.py#L79-L88) asserts every FR-2 field on the happy path.

### F-4 — CLOSED at code level (correctness / FR-5)

- **Path**: [services/mcp-server/src/agentrise_mcp/tools/push_activity.py](services/mcp-server/src/agentrise_mcp/tools/push_activity.py#L177-L200), [services/mcp-server/src/agentrise_mcp/tools/push_artifacts.py](services/mcp-server/src/agentrise_mcp/tools/push_artifacts.py#L188-L204)
- **Evidence**: Both tools branch on `resp.status_code in (401, 403)` BEFORE the generic 4xx/5xx path. `error_label = "unauthorized" if resp.status_code == 401 else "forbidden"`. For `push_activity` the auth-failure envelope carries the full FR-5 aggregate: `batches_sent, batches_failed, files_read, rows_read, inserted, updated, rejected, rollups`. For `push_artifacts` the envelope carries `batches_sent: 1, batches_failed: 1, inserted: 0` per the contract block in `api.md#mcp-tools`.
- **Contract evidence**: `api.md#mcp-tools` auth-failure envelopes now document `error: "unauthorized" | "forbidden", http_status: 401 | 403` with the full aggregate for `push_activity` and the fixed shape for `push_artifacts`.
- **Test caveat**: coverage gap surfaces as F-10 below — the 403 branch has no test and the FR-5 aggregate fields are asserted only for the happy 401 case's `success/error/http_status` triplet. Does NOT re-open F-4 (code is correct), but does not lock the FR-5 contract either.

### F-5 — CLOSED (correctness / FR-6)

- **Path**: [services/mcp-server/src/agentrise_mcp/tools/push_activity.py](services/mcp-server/src/agentrise_mcp/tools/push_activity.py#L52-L56) and [L73-L76](services/mcp-server/src/agentrise_mcp/tools/push_activity.py#L73-L76), [services/mcp-server/src/agentrise_mcp/tools/push_artifacts.py](services/mcp-server/src/agentrise_mcp/tools/push_artifacts.py#L87-L91) and [L100-L103](services/mcp-server/src/agentrise_mcp/tools/push_artifacts.py#L100-L103)
- **Evidence**: `_MISSING_TOKEN_ENVELOPE = {"success": False, "error": "missing_ingest_token", "message": "Set AGENTRISE_INGEST_TOKEN before invoking this tool."}` is returned as a fresh `dict(...)` copy on any `ConfigError` — no leakage of the `ConfigError`'s string, and both tools use the identical constant. Matches PRD FR-6 and D-06 verbatim.
- **Test evidence**: [test_push_activity_missing_token.py](services/mcp-server/tests/unit/test_push_activity_missing_token.py#L28-L32) asserts `result["error"] == "missing_ingest_token"` AND `result["message"] == "Set AGENTRISE_INGEST_TOKEN before invoking this tool."` verbatim; `assert respx_mock.calls.call_count == 0` confirms no HTTP path is touched.

## Regression sweep — NEW findings

### F-9 — MEDIUM — scope-creep: 5 stray `.py.new` test files uncommitted in the working tree

- Category: scope-creep / hygiene
- Paths:
  - services/mcp-server/tests/unit/test_push_activity_auth_failure.py.new
  - services/mcp-server/tests/unit/test_push_activity_missing_token.py.new
  - services/mcp-server/tests/unit/test_push_artifacts_auth_failure.py.new
  - services/mcp-server/tests/unit/test_push_artifacts_missing_token.py.new
  - services/mcp-server/tests/unit/test_push_artifacts.py.new
- Source: PLAN §5 `file_plan` for T-08 lists the `.py` test files, not `.py.new` siblings. `git status` shows the whole `services/mcp-server/tests/unit/` directory as `??` (untracked), so these are stray working-tree artefacts.
- Description: The five `.py.new` files are clearly the intended replacements produced during the fix pass — a diff shows them adding the FR-5-envelope assertions and a `test_403_forbidden` case that the current `.py` files lack. They were not renamed over the originals, so the stronger assertions never run. Leaving them in-tree is (a) confusing for anyone reading the review artefacts and (b) hides the coverage gap that F-10 records.
- Suggested fix: promote each `.py.new` → `.py` (`mv` overwrite) if the intent is to lock in the stronger assertions, then re-run pytest; OR delete the `.py.new` files if the current `.py` shape is intentional. Do not leave both.

### F-10 — MEDIUM — testability: FR-5 auth-failure envelope + 403 branch under-asserted

- Category: testability / test-plan
- Paths: [services/mcp-server/tests/unit/test_push_activity_auth_failure.py](services/mcp-server/tests/unit/test_push_activity_auth_failure.py#L45-L97), [services/mcp-server/tests/unit/test_push_artifacts_auth_failure.py](services/mcp-server/tests/unit/test_push_artifacts_auth_failure.py#L1-L60)
- Source: PRD FR-5; PLAN §5 T-08 test list
- Description: The code closes F-4 by returning the full FR-5 aggregate on 401/403 (see closure note above), but the tests only assert `success`, `error`, `http_status`, and route call-count. The FR-5 aggregate fields (`batches_sent`, `batches_failed`, `files_read`, `rows_read`, `inserted`, `updated`, `rejected`, `rollups` for `push_activity`; `batches_sent`, `batches_failed`, `inserted` for `push_artifacts`) are not asserted anywhere in the `.py` test files. No test exercises the 403 → `"forbidden"` branch at all — only 401 is tested. A future refactor could drop the aggregate fields or misroute 403 and every test still passes. The stray `.py.new` files (see F-9) contain the exact assertions that would lock this — promoting them closes both findings.
- Suggested fix: add three assertions per auth-failure test — `assert result["batches_sent"] == …`, `assert result["batches_failed"] == …`, and one aggregate counter — and add `test_403_forbidden` in both auth-failure files (401 fixture with status 403 and a `error == "forbidden"` assertion). The `.py.new` files already contain acceptable versions of both.

## Regression sweep — clean dimensions

- **Correctness (non-F-4)** — `push_activity` FR-2 envelope, `push_artifacts` FR-3 envelope + FR-7/FR-8 abort, FR-6 fail-fast on missing token all still hold; no new deviations.
- **Architecture / ADR** — ADR-0013 URLs still pinned as module constants (`_INGEST_ACTIVITY_PATH`, `_INGEST_ARTIFACTS_PATH`); ADR-0014 sibling-deploy honored (no wiring into `docs/config/project-commands.yaml::preflight`); D-04 single-source YAML unchanged; D-05 500-row MCP cap comment reiterates it is unrelated to backend's 2730-row DB chunk. Nothing regressed.
- **Security (R-06)** — glob + JSON-key allowlists still enforced at YAML parse time AND at every resolver entry point (`glob_count.py`, `json_key_count.py`, `json_field_sum.py`). `AllowlistError` still aborts the whole `push_artifacts` POST with `{success:false, error:"unsafe_glob_pattern"|"unsafe_json_key", entry_key, offending_value}` — matches FR-7/FR-8 + api.md contract.
- **Security (R-07)** — `TokenSuppressionFilter` still installed on `core/logging.py`; `Config.__repr__`/`__str__` redaction, `HttpClient.__repr__` redaction, and `HttpClient.__getstate__` pickle-block all still present. Token still not passed into any `extra=` dict on the FR-5 auth-fail path.
- **Reliability** — retry policy in `core/http_client.py` unchanged: 5s connect / 30s total, 3 attempts, exponential + jitter, retries only on `NETWORK_RETRY_EXCEPTIONS`, terminal on any 4xx/5xx.
- **Pattern adherence** — event names in `push_activity.py` (`push_activity_started` / `_completed` / `_batch_failed` / `_auth_failed`) now match the PRD § NFR-Observability convention and the `_ALLOWED_EVENTS` allowlist in `core/logging.py`. The T-05 rename claim in the round-2 context checks out.
- **Contract shape** — `docs/requirements/api.md#mcp-tools` now describes `push_activity` and `push_artifacts` signatures + success/auth-fail/missing-token/allowlist envelopes matching the code. No drift in either direction.

## Carry-forward from round 1 (unchanged)

### F-6 — MEDIUM — design-patterns: sync tool bodies vs `async` signatures pinned by PLAN §3

Still applies — implementation remains synchronous (`def push_activity`, `httpx.Client`, `time.sleep` backoff) against PLAN §3's `async` pin and the PRD's shared-`httpx.AsyncClient` sketch. Non-blocking on its own; either refactor to async or promote a new DECISIONS entry.

### F-7 — LOW — scope-creep: `docs/stories/ING-04.md` gains tracker header lines

Still applies — three tracker-reference lines added to the story front matter are outside every T-NN `files[]`. Orchestrator-driven, flag once.

### F-8 — LOW — scope-creep: `docs/activity/activity.jsonl` auto-appended by harness hooks

Still applies — hook-managed harness state, not source under review. Leave in place.

## Recommendation

**PASS WITH WARNINGS.** F-1..F-5 closed at code + produced-contract level. Two MEDIUM regressions (F-9 stray `.py.new` files, F-10 FR-5-envelope coverage gap + missing 403 test) can ride as PR-body warnings but SHOULD be resolved before merge — promoting the `.py.new` files closes both simultaneously and locks in the FR-5 assertions that round-1 F-4 was meant to enforce. F-6 (MEDIUM) and F-7/F-8 (LOW) unchanged from round 1.

Snapshot hash echoed for auditability: `dd7536287d525e90c8f701e34cd0591d441aa49ef72a759c318d81a72c1b3b12`.
