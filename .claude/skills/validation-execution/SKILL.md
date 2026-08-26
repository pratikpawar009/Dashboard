---
name: validation-execution
description: Run feature validation — environment preflight, flows, stack smoke, run-all, test-case JSON update, consolidated report. Used by validation-agent.
user-invocable: false
---
# Validation execution

The method for validating a feature end-to-end. Apply the phases in order; never stop on the first failure — collect everything for one consolidated report.

Phase numbering used throughout: 1 = Environment check, 2 = Write/load flows, 2b = Stack smoke, 3 = Run all flows, 3b = Contract conformance, 4 = Update test-case JSON, 5 = Consolidated report.

## Environment check

Goal: confirm the runtime is up AND all dependencies are installed before running flows. Do not "mock your way out" of any failure here.

This phase catches the most common cascade-failure class: tests fail in round 1 because a dep was missing; team installs it; round 2 surfaces the NEXT missing dep; cycle repeats. Running preflight here surfaces ALL missing deps up front in one shot.

### Step 1 — Preflight (mandatory)

Read `docs/config/project-commands.yaml` for the `preflight:` list. If absent or empty AND any stack in `harness.yaml` declares a `framework` that produces a runnable surface (the patterns skill for that framework will tell you): FAIL Phase 1 with `preflight-not-configured — run /arh-init to capture or edit docs/config/project-commands.yaml preflight:`.

For each preflight command:

1. Run with 120s timeout. Capture stdout + stderr.
2. Non-zero exit → FAIL Phase 1. Print the command, last 500 chars of stderr, and which preflight step failed.
3. Do NOT proceed to Step 2 until all preflight commands return 0.

What belongs in `preflight:` (general shape, not stack-specific examples):

- Package-manager install command (`<pm> install --frozen-lockfile` or equivalent — pins lockfile version)
- Dep-sync / lock-resolve for any language that has separate "install vs sync" (`uv sync`, `bundle install`, `go mod download`, etc.)
- Smoke-import of any deps known to fail silently (async DB drivers, mail libs, validators) — invoked through the runtime's `-c "import <pkg>"` equivalent
- Browser / device install for test-running stacks (consult the runner's CLI for its install command)
- Port-free check for every port a stack will bind (from `stack-smoke.md` `Run:` lines): a squatter process means the later "started" signal may be a stale server, not your build. On conflict print the PID + owning command and stop — never silently reuse whatever is already listening. Prefer binding explicit `127.0.0.1` over hostnames that may resolve to `::1` (IPv4/IPv6 mismatch between server and test runner is a known false-FAIL source)

If a preflight failure surfaces a missing dep that was NOT in `project-commands.yaml preflight:`, the fix is two-step:
1. Install the dep
2. Add the install command to `project-commands.yaml preflight:` so future runs catch it. This is a "lesson learned" capture (no separate command needed; just edit the YAML).

### Step 2 — Generic checks (every stack)

- Required env vars set per `harness.yaml`. Surface the exact missing names.
- The endpoints under test are reachable (HTTP HEAD or equivalent).
- Test users / fixtures available; credentials valid.

### Step 3 — Stack-specific checks

For each runnable stack declared in `harness.yaml`, confirm its dev surface is up:

- Web frameworks: dev-server process is running on its configured port
- API frameworks: server process is running; any pending DB migrations have been applied
- Mobile frameworks: device or simulator is connected; auth is real, not mocked
- E2E runners: browsers / drivers are installed
- Database-backed tests: containers or local services are up

Consult the `<framework>-patterns/SKILL.md` body for each stack's specific check command. When patterns skill is scaffold-TODO, fall back to the framework's canonical "is it running" check (curl against the dev port or pgrep for the process name).

### Escalation matrix

| Symptom                              | Action                                    |
|--------------------------------------|-------------------------------------------|
| `preflight:` key missing             | Abort: `preflight-not-configured — run /arh-init to capture` |
| Preflight command exits non-zero     | Abort, print failed command + last 500 chars stderr |
| Test case JSON missing               | Abort: `Run /arh-plan-requirements first`     |
| Required env var missing             | Abort, list var names                     |
| Endpoint unreachable                 | Abort, print URL + last response          |
| App fails to launch                  | Abort with the build error                |
| Mobile device unavailable            | Abort: `Connect device or start simulator`|

Do not silently switch to mocks. Validation depends on real behaviour.

### Output

```
Environment OK.
  Preflight: <N> commands passed in <T>s
  Endpoints: <N> reachable
  Env vars:  <N> set
  Devices:   <N> connected (mobile)
```


## Write or load flows

Goal: ensure a runnable flow exists for every TC where `automatable: true`.

`--rerun` mode skips generation; reuse existing files.

### Generation mode

For each TC where `automatable: true`:

1. Determine the runner from the TC's `type` and the project's stack:

   | TC `type`    | Default runner per stack                                                   |
   |--------------|----------------------------------------------------------------------------|
   | `e2e`        | playwright (web) / maestro (mobile) / cypress (legacy web)                 |
   | `integration`| pytest (python) / vitest+supertest (node) / go-test (go)                   |
   | `unit`       | jest / vitest / pytest / go-test                                           |
   | `performance`| k6 / locust                                                                 |
   | `security`   | manual checklist (do not auto-generate)                                    |
   | `contract`   | dredd / pact / openapi-validator                                            |

2. Write the flow file at the canonical path:

   - Playwright: `tests/e2e/<TC-id>.spec.ts`
   - Maestro:    `e2e/<TC-id>.yaml`
   - pytest:     `tests/integration/test_<TC-id>.py`
   - k6:         `tests/perf/<TC-id>.k6.js`

3. Patch the TC entry in `docs/test-cases/$ARGUMENTS.json` to set `flow_path: "<the path above>"`.

4. Each flow asserts the TC's `then` clause exactly. Do not invent additional assertions.

### Rerun mode

Skip generation. Validate that every `automatable: true` TC has a `flow_path` and that the file exists. Surface any orphans.

### Anti-pattern

- Don't combine multiple TCs into one flow file. One TC, one flow — failure attribution depends on it.
- Don't generate for TCs marked `manual: true`. They go to the human follow-up list in Phase 5.


## Stack smoke

Goal: verify the **real application** starts, applies migrations, and answers a health check BEFORE running any flow. Catches "tests pass but the server never booted" — a class of failures the test-runner alone cannot detect (in-memory test DBs silently pass while the real migration would fail; mocked-fetch unit tests pass while the real backend rejects requests).

Disabled when `harness.yaml outputs.validation.stack_smoke: false`. Default `true`.

### Why this phase exists

Common failure mode: `/arh-validate-feature` reports PASS while the frontend never connected to the new backend (it kept hitting a stale server on the old port). Unit tests pass on the in-memory DB. No step in the validation pipeline started the **actual** new server, ran the **actual** migration, or hit the **actual** `/health` endpoint. Result: shipped broken with no warning.

Mitigation: spawn the real server, poll the healthcheck endpoint until it returns 200, then run HTTP assertions. If the server doesn't return a healthy response within the configured timeout, validation fails before any flow runs.

### Procedure

Read `docs/config/stack-smoke.md`. Each `# <stack-id>` section maps to one stack in `harness.yaml`. Bullets per section:

- `Deps:` (optional) — backing-service start command(s) this stack needs (DB / cache / queue), run BEFORE `Migrate:`. A list — run each in order. An entry starting `(external — …)` → skip (assume already running). `[NEEDS CLARIFICATION …]` → FAIL the section with `sub_step: deps`.
- `Run:` (mandatory) — direct dev-server command
- `Docker:` (mandatory) — containerized equivalent OR `(n/a — <reason>)` to skip
- `Migrate:` (optional) — schema migration command, run BEFORE `Run:` / `Docker:`
- `Check:` (optional) — explicit healthcheck URL; defaults to `http://127.0.0.1:<port>/health` derived from the `--port <N>` flag in the `Run:` / `Docker:` command

For each section:

1. **Pick command**: prefer `Docker:` (hermetic, isolated). Fall back to `Run:` when `Docker:` is `(n/a — ...)`. Skip stack entirely when both are `(n/a — ...)`.
2. **Deps** (if `Deps:` bullet present): run each start command in order with 60s timeout; capture exit code. Skip any entry the picked `Run:`/`Docker:` command already starts (a full `docker compose up` brings its own services — starting them again collides on the port). A non-zero exit, or a `[NEEDS CLARIFICATION …]` placeholder, → FAIL the section with `sub_step: deps` (never run flows against an absent dependency). `(external — …)` entries are skipped, not failed.
3. **Migrate** (if `Migrate:` bullet present): run with 60s timeout; capture exit code.
4. **Start**: run picked command as a background process; capture PID; redirect stdout/stderr to `tmp/smoke-<stack-id>.log`.
5. **Wait-for-boot**: poll healthcheck URL with 0.5s interval. Connection-refused → retry. 200 → ready. Any other non-2xx after 30s → FAIL with last response captured.
6. **Verdict**: record `{status, sub_step, duration_ms, log_tail}` per stack.
7. **Stop**: `kill $PID` (or `docker compose down <service>` when Docker path used); also tear down any services started in step 2 (`docker compose down` / `kill`). Registered as `trap` to fire even on script abort. Cleanup `tmp/smoke-*.log` files only when verdict is PASS (keep on FAIL for the report).

Hard-coded timeouts (no per-stack override): start_wait_s=30, migrate_s=60, healthcheck_s=10. Teams override the entire phase via `harness.yaml outputs.validation.stack_smoke: false` if these don't fit.

### Per-TC schema (last_run.stack_smoke)

Added to `docs/test-cases/<story>.json` at validate-feature Phase 4:

```json
{
  "last_run": {
    "stack_smoke": {
      "status":   "PASS | FAIL | SKIPPED",
      "sub_step": "deps | start | migrate | healthcheck | none",
      "duration_ms": 4231,
      "log_tail": "<last 500 chars of stdout/stderr on FAIL; null on PASS>"
    }
  }
}
```

`stack_smoke.status: SKIPPED` when both `Run:` and `Docker:` bullets are `(n/a — ...)` (pure library stack, mobile/desktop without serve-on-port mode) — the verdict is PASS-equivalent for ranking.

### Verdict propagation

Any stack-smoke FAIL → Phase 3 (run flows) is SKIPPED for that stack; report verdict drops to FAIL with the sub-step that broke. Other stacks may still proceed (e.g. backend smoke fails → backend flows skipped; frontend smoke passes → frontend flows still run with mocked backend).

| stack-smoke result | Phase 3 action | Phase 5 verdict (overall) |
|---|---|---|
| All stacks PASS | Run all flows normally | per existing rules |
| Some stack FAIL | Skip flows for failed stack(s); run others | At least PARTIAL; FAIL if any flow requires the failed stack |
| All stacks FAIL | Skip all flows | FAIL with `stack-smoke: <details>` as primary cause |

### Anti-pattern

- **Don't mock /health.** If the agent decides "the health endpoint is fake-implemented in tests so smoke should mock it too", that defeats the entire phase. The point is to hit the real running server.
- **Don't skip smoke to save time on a slow startup.** A 30-second cold start beats a shipped broken feature. If startup is genuinely too slow, prefix it with a smaller "ping" service or fix the boot path.
- **Don't pre-migrate the DB before smoke.** The migration is part of the smoke. If migrations fail on a fresh DB, that's a real failure mode that must surface.
- **Don't run smoke against the user's dev DB.** Smoke runs against an ephemeral local DB (Postgres in Docker, sqlite for portable stacks). Production DB is never touched.


## Run all flows

Goal: execute every automatable flow and collect every result. Never stop on first failure. Retry FAILed/ERRORed TCs to distinguish flakes from real bugs. Compare measured values against NFR performance budgets.

### Procedure

For each runner with at least one flow:

1. Invoke the runner's CLI (from `docs/config/project-commands.yaml`):
   - `playwright`: `pnpm exec playwright test tests/e2e/<TC-id>.spec.ts`
   - `maestro`: `maestro test e2e/<TC-id>.yaml`
   - `pytest`: `pytest tests/integration/test_<TC-id>.py -q`
   - `k6`: `k6 run tests/perf/<TC-id>.k6.js`

2. Capture, per TC:
   - PASS / FAIL / ERROR (timeout, crash, infra)
   - Steps executed
   - Expected vs actual
   - Screenshot path or trace artefact (when produced)
   - Failure reason (one line)

3. **Continue past failures.** A FAIL or ERROR on TC-03 must not block TC-04.

### Retry-on-flake (V1)

Read retry count from `harness.yaml outputs.validation.retry_count` (default `2`, `0` disables, capped at `5`).

For every TC whose first attempt status is `FAIL` or `ERROR`:

1. Re-run up to `retry_count` additional times.
2. Record each attempt in an `attempts` array: `[{n: 1, status: "FAIL", reason: "..."}, {n: 2, status: "PASS"}]`.
3. Compute `verdict` from the attempt history:
   - `PASS` — first attempt PASS, OR retry attempts all PASS.
   - `FLAKY` — at least one PASS across attempts, but not all attempts PASS.
   - `FAIL` — all attempts FAIL or ERROR.
4. The `last_run.status` field carries the **final attempt's** status; the `verdict` field carries the flake-aware judgement.

FLAKY verdicts surface as warnings in Phase 5, not as failures, but they are listed in a dedicated `## Flaky tests` section so the team can stabilise them.

Set `outputs.validation.retry_count: 0` in `harness.yaml` to disable retries entirely (e.g. for deterministic CI environments where a flake IS a bug).

### Performance budget enforcement (V3)

For every TC where `type: performance`:

1. Parse the TC's `requirement_id` from the JSON; look up the matching NFR in REQUIREMENTS.md.
2. Extract the budget value (e.g. `p95 < 250ms @ 100 RPS` from NFR-perf body).
3. Extract the measured value from the runner output (k6 prints p50/p95/p99; pytest-benchmark prints mean/stddev; playwright `--trace` includes timings).
4. Record:
   ```json
   "budget": {
     "target":   "<verbatim NFR budget string>",
     "measured": "<measured value with units>",
     "budget_pass": <bool>
   }
   ```
5. `budget_pass: false` does NOT cause the TC to FAIL (the TC's own assertions may still pass). It DOES drop the overall verdict to PARTIAL minimum at Phase 5.

When the NFR cannot be parsed (freeform text, no extractable number), record `budget: {"target": "<text>", "measured": null, "budget_pass": null}` and flag the NFR in Phase 5 as `budget-unparseable`. Do NOT fabricate a value.

### Parallelism

Default to the runner's native parallel mode. Do not over-parallelise mobile (max 1 device at a time unless the device farm supports it). Retries respect the same parallelism setting.

### Output

Per-runner summary printed live; full structured results (including `attempts` and `budget` blocks) held in memory for Phase 4.


## Contract conformance

Goal: confirm every shared contract this story **produces** still matches what it shipped — so a consuming story never binds to a stale record. Runs only for contracts whose `produced_by` is `$ARGUMENTS`; skip silently if the story produces none.

### Procedure

1. Find produced contracts: grep `docs/requirements/*.md` for `### <name>` sections whose `produced_by: $ARGUMENTS`.
2. For each, compare the shipped surface to the section's `shape`, dispatched by the file (`<kind>` = filename):
   - `api.md`  → the **live** endpoint (from Phase 2b/3, or `GET /openapi.json`): method, path, request fields, response fields, status→error mapping.
   - `data.md` → the shipped migration / ORM model: table, columns, **nullability**, constraints. *(This is the class that produced the promo NOT-NULL-vs-nullable drift.)*
   - `auth.md` → the token claim shape the service issues / verifies.
   - `event.md` → the payload the publisher emits.
3. Any field in one but not the other, or a mismatched type / nullability / status code → record a `contract-conformance` finding: contract name, the field, recorded-vs-shipped.

### Verdict

A conformance finding drops the Phase-5 verdict to **FAIL** — record and code disagree, so some consumer is being lied to. Fix is one of: update the `docs/requirements/<kind>.md` section to match the shipped surface (the common case — the contract drifted), or fix the code if the shipped surface is wrong. Never "resolve" it by deleting the contract.


## Update test-case JSON

Goal: write each run's outcome back into `docs/test-cases/$ARGUMENTS.json` so the file is always the source of truth. The patch carries attempt history, flake-aware verdict, and (for performance TCs) the budget comparison block.

### Per-TC patch

For each automatable TC, set or replace:

```json
{
  "id": "$ARGUMENTS-TC-03",
  "...": "...",
  "last_run": {
    "started_at":     "<iso8601>",
    "duration_ms":    1234,
    "status":         "PASS | FAIL | ERROR",
    "verdict":        "PASS | FAIL | FLAKY",
    "attempts": [
      {"n": 1, "status": "FAIL", "duration_ms": 1100, "reason": "assertion: status code 400 != 200"},
      {"n": 2, "status": "PASS", "duration_ms": 1234, "reason": null}
    ],
    "budget": {
      "target":      "p95 < 250ms @ 100 RPS",
      "measured":    "p95 = 312ms @ 100 RPS",
      "budget_pass": false
    },
    "failure_reason": "<one line; null when verdict is PASS or FLAKY-final-PASS>",
    "artefact":       "tests/e2e/output/<TC-id>/arh-trace.zip",
    "runner":         "playwright | maestro | pytest | k6",
    "rerun_count":    1
  }
}
```

### Field rules

- `status`: the **final attempt's** raw outcome (PASS / FAIL / ERROR). Carries forward for backwards compatibility with existing readers.
- `verdict` (V1): flake-aware judgement computed from `attempts`. PASS = all attempts PASS or first attempt PASS. FLAKY = mixed across attempts. FAIL = all attempts FAIL/ERROR.
- `attempts[]` (V1): one row per execution attempt. The first row is the original run; subsequent rows are retries triggered by Phase 3 retry-on-flake.
- `budget` (V3): only present when `type: performance`. `budget_pass: null` when the NFR cannot be parsed; flag in Phase 5 as `budget-unparseable`.
- `failure_reason`: kept for compatibility — set to the last failing attempt's reason when verdict is FAIL or FLAKY; null when verdict is PASS.

### Rules

- Append to a `runs` array if the project tracks history; otherwise overwrite `last_run`.
- Never remove a TC from the JSON because it failed. Only the `last_run` mutates.
- Manual TCs keep `last_run: null`. The Phase 5 report lists them under `Manual follow-up`.
- **`--rerun-failed` mode (V2)**: patch only TCs whose previous `last_run.verdict != "PASS"` (or `last_run` absent). Untouched TCs keep their prior `last_run` block.

### Validation of the JSON

After patching, run a JSON-schema check (`jsonschema`) to catch corruption from interrupted writes. If invalid, restore from the in-memory copy and warn.


## Consolidated report

Goal: produce a single human-readable report with structured per-failure bug blocks. Path: `docs/features/$ARGUMENTS/VALIDATION-<YYYYMMDD-HHMM>.md`.

### Report structure

```
# Validation report — $ARGUMENTS

- Date: <iso8601>
- Verdict: PASS | PARTIAL | FAIL
- Mode: full | rerun | rerun-failed
- Total: <T>   Passed: <P>   Failed: <F>   Errored: <E>   Flaky: <Fk>   Skipped manual: <M>
- Duration: <total seconds>

### Summary

| Layer        | Total | Pass | Fail | Error | Flaky |
|--------------|-------|------|------|-------|-------|
| Stack smoke  |   2   |   2  |   0  |   0   |   0   |
| Unit         |  12   |  12  |   0  |   0   |   0   |
| Integration  |   8   |   7  |   1  |   0   |   0   |
| E2E          |   5   |   3  |   1  |   1   |   1   |
| Performance  |   1   |   0  |   0  |   0   |   0   |  ← budget_pass: false

Contract-conformance findings (Phase 3b) are listed in `## Failed (bug blocks)` with `contract-conformance` as the failure class (contract name + recorded-vs-shipped field) and drop the verdict to FAIL.

Stack-smoke row counts one entry per stack in `docs/config/stack-smoke.md`. A stack with both `Run:` and `Docker:` bullets set to `(n/a — ...)` counts under SKIPPED. The verdict justification line names any FAIL: `Verdict: FAIL — stack-smoke api/healthcheck`. All-SKIPPED on a multi-service project drops verdict to PARTIAL with note `stack-smoke-not-configured`. Per-stack failure detail (last response, log tail) goes in the `## Failed (bug blocks)` section below, same shape as TC failures.

### Task completion verification (MANDATORY)

Cross-check every entry in `docs/features/<id>/tasks.json` `tasks[]` against on-disk artifacts. Catches the silent-skip failure mode where the plan listed a documentation or doc-section task; implementation skipped it; nobody noticed. Read the tasks from `tasks.json`, never from PLAN.md — §5 there is a one-line pointer to this file, so a PLAN-shaped read finds zero rows and silently skips this mandatory check.

| Task | Target file | Existence | Section match | Verdict |
|------|-------------|-----------|---------------|---------|
| T-NN | `<path>` (description) | ✓ | ✓ | PASS |
| T-NN | `<path>` (`<expected section>`) | ✓ | **MISSING** | **FAIL** |
| T-NN | `<path>` (description) | — | — | **FAIL (blocked: <reason>)** |
| T-NN | `<path>` (description) | — | — | N/A (skipped) |

Rules:
- `Target file` — each `F-NN` in the task's `files[]`, resolved to a path through `file_plan`
- `Existence` — every resolved path exists on disk after implementation
- `Section match` — for tasks whose `title` / `notes` read "Add <X> section" / "update <Y> section" / "include <Z>", grep the resolved path(s) for the section heading or cited identifier
- A task with `status: blocked` is work that did **not** happen — its own or a predecessor's — so it is a **FAIL**, quoting the task's `reason` so the report separates an upstream block from a silent miss. Do **not** exempt the status: `/arh-implement` Step 1 cascades `blocked` onto every dependent of a blocked task, so exempting it would hide an entire never-attempted subtree behind the one escalation the engineer already acknowledged
- A task with `status: skipped` is a deliberate decision rather than missing work → `Verdict: N/A (skipped)`, which does not drop the report verdict. Never silently omit its row
- `Verdict: FAIL` for any task drops report verdict to PARTIAL minimum and lists the failed task IDs in the verdict justification. Fix-loop consumes these as additional failure entries
- Tasks marked `chore` or `test` verified by file-existence only; doc tasks (`docs(...)`) verified by section-heading grep

### Passed
| TC id            | Title                                  |
|------------------|----------------------------------------|
| $ARGUMENTS-TC-01 | Apply valid promo code                 |
| ...

### Flaky tests (V1)

TCs that passed on retry but failed on at least one attempt. Surfacing them here so the team can stabilise them — they do NOT block PASS verdict.

### $ARGUMENTS-TC-09 — Browser crash mid-flow

- Attempt history: FAIL (1100ms) → PASS (1234ms)
- Final verdict: FLAKY
- Likely cause: dev server cold start; consider warmup hook in Phase 1

### Performance budget breaches (V3)

Performance TCs whose measured value exceeded the NFR-perf budget. Drops verdict to PARTIAL minimum even when the TC's own assertions pass.

### $ARGUMENTS-TC-12 — Promo preview latency  (NFR-perf)

- Target:   p95 < 250ms @ 100 RPS
- Measured: p95 = 312ms @ 100 RPS
- budget_pass: false
- Action: investigate before merge; widen budget in PRD OR add caching as ADR

### Regression coverage (V4)

TCs tagged `regression-<original-TC-id>` from prior fix-loop passes. These exist to keep specific bugs from re-surfacing.

| Regression TC      | Guards against | Last attempt | Verdict |
|--------------------|----------------|--------------|---------|
| $ARGUMENTS-TC-15   | TC-03 (expired code returns 200) | PASS  | PASS    |
| $ARGUMENTS-TC-16   | TC-07 (used code accepted twice) | FAIL  | **FAIL** |

A regression-tagged TC that fails AGAIN is automatic PARTIAL — the bug has re-surfaced. Highlight prominently and feed into the next fix loop.

### Failed (bug blocks)

### $ARGUMENTS-TC-03 — Apply expired promo code  (Priority: Must)

- AC: Given an expired code, when applied, then status 400 with message "expired".
- Attempts: 2 (all FAIL)
- Steps executed:
  1. POST /promos/preview with expired code
  2. Inspect response
- Expected: HTTP 400, body.message="expired"
- Actual:   HTTP 200, body.message=null
- Failure reason: server returns success for expired codes
- Artefact: tests/e2e/output/TC-03/arh-trace.zip
- Likely cause: `isExpired` check missing in promoStack.ts

### $ARGUMENTS-TC-07 — Apply already-used code  (Priority: Must)
...

### Errored

### $ARGUMENTS-TC-09 — Browser crash mid-flow

- Reason: Playwright reported `browserContext closed`
- Likely cause: dev server OOM at iteration 4
- Action: re-run after restarting `pnpm dev`

### Manual follow-up

These TCs require human verification (no automation):

- $ARGUMENTS-TC-10 — Visual regression review
- $ARGUMENTS-TC-11 — A11y screen-reader walk-through

Each manual TC without a recorded result produces a `.pending_carry_forward` entry:

```json
{
  "item_id":     "$ARGUMENTS-TC-10",
  "kind":        "test_case",
  "reason":      "Manual TC — Visual regression review; no recorded result",
  "owner":       "<owner from PRD or test-case JSON>",
  "added_at":    "<iso8601>",
  "added_by":    "validate-feature/05-report (manual TC pending)",
  "resolved_at": null,
  "evidence":    null
}
```

**Where this entry is written is mode-conditional:**

- **Standalone `/arh-validate-feature`** — write the entry directly to `docs/features/$ARGUMENTS/state.json` at `.pending_carry_forward`, as today. This invocation is the single writer of that file, so self-writing is safe.
- **GATE MODE (invoked by `/arh-implement`'s Validate ∥ Review gate, signaled by the orchestrator's `GATE MODE — report-only` directive in your invocation)** — do NOT write `state.json`. Write ONLY `VALIDATION-<date>.md` plus the test-case JSON, then RETURN the verdict + carry-forward entries to the orchestrator. The orchestrator dispatches validation-agent and code-review-agent in a single message (two Task calls), both READ-ONLY on the source tree; it is the single writer that applies `.pending_carry_forward` (and every other `state.json` / `features.json` write) AFTER the join. Deferring the write here prevents a concurrent read-modify-write race with code-review-agent on the same `state.json`.

Entries surface in `/arh-implement` Step 5 commit-PR gate and `/arh-review`. To resolve:
`harness carry-forward resolve <item_id> --evidence <path-to-manual-test-log>`.

### Budget-unparseable NFRs (V3)

NFRs whose budget string could not be parsed into a numeric comparison. Validation could not enforce these — flag for team review.

- NFR-perf-startup: `Cold start should feel fast` — no numeric budget; rewrite to `p95 cold-start < 1500ms`.

### Proof of run (MANDATORY footer)

```
### Proof of run

- session_id:        <Claude Code session id>
- bash_invocations:  <count of Bash tool calls in this validation>
- test_runner_runs:  <count of pytest/playwright/vitest invocations>
- stack_smoke_runs:  <count of start/healthcheck pairs>
- duration_seconds:  <wall-clock from validation start to report write>
- timestamp:         <iso8601>
```

Makes "report claims tests passed but no agent JSONL shows runs" detectable by `/arh-review`. A report with `bash_invocations: 0` or `test_runner_runs: 0` while claiming PASS is auto-flagged as suspicious.
```

### Verdict rule (updated for V1 + V3 + V4 + stack-smoke + task-completion)

- `PASS` —
  - every automatable TC's `verdict` is `PASS` OR `FLAKY` (with at least one successful attempt), AND
  - every performance TC has `budget_pass: true`, AND
  - no regression-tagged TC has `verdict: FAIL`, AND
  - Summary `Stack smoke` row has zero FAIL/Error AND not all-SKIPPED on a multi-service project, AND
  - every PLAN task in `## Task completion verification` has `Verdict: PASS`, AND
  - manual TCs are not blocking.

- `PARTIAL` —
  - at least one automatable TC has `verdict: FAIL`, OR
  - any performance TC has `budget_pass: false`, OR
  - any regression-tagged TC has `verdict: FAIL` (bug has re-surfaced — escalate prominently), OR
  - Summary `Stack smoke` row is all-SKIPPED on a multi-service project (`stack-smoke-not-configured`), OR
  - any PLAN task in `## Task completion verification` has `Verdict: FAIL`.

- `FAIL` —
  - error rate >25% across automatable TCs, OR
  - Summary `Stack smoke` row has any Fail (verdict line cites `stack-smoke: <stack>/<sub-step>`), OR
  - environment-level failure (preflight failed in Phase 1);
  - halt before review.

The `/arh-implement` orchestrator's Step 3 (fix loop) consumes the failed TC bug blocks verbatim. Regression re-failures, budget breaches, task-completion failures, and stack-smoke failures all feed back to the fix loop as new failure entries.

