---
name: evidence-pass
description: Run six-dimension evidence (typecheck/unit/lint/runtime/compile/design) at end of `/arh-implement` Step 1 — each PASS/FAIL(≤3 rounds)/N/A. Writes state `.impl_evidence`; gates validation + commit.
when_to_use: Loaded by the implementation-agent at end of task implementation, BEFORE it returns control to `/arh-implement`. The agent runs the packet once after all tasks are `done`. If any dimension is FAIL, the agent fixes the cause (mirroring Step 3's anti-suppression rules), re-runs the FULL packet, and repeats up to 3 rounds. On round-3 FAIL the agent writes `EVIDENCE-ESCALATION.md` and returns BLOCKED. Not invoked outside `/arh-implement` — `/arh-validate-feature`'s preflight reads the packet but does NOT regenerate it.
user-invocable: false
allowed-tools: Read Write Edit Bash Grep Glob
---
# evidence-pass — handover receipt for /arh-implement

## Why this skill exists

`/arh-implement` Step 1 today hands over to validation with prose: "implementation complete." Three failure modes fall out:

- *No artefact proves checks ran.* The agent's claim is the only record.
- *Static checks miss runtime errors.* Code compiles + lints clean but the app fails to boot.
- *Reviewers and `/arh-security-review` have nothing to audit.* They read prose.

The evidence pass closes all three. The implementation-agent runs the six-dimension packet itself, fixes any FAIL internally before declaring "tasks complete," and writes a machine-readable receipt to state. Downstream `/arh-validate-feature` Step 0 and `/arh-implement` Step 5 (RC5) read the same record. Reviewers spot-check `evidence/*.log` files instead of trusting prose.

## When the agent invokes it

End of Step 1, after every task in `tasks.json` `tasks` has `status: done | blocked | skipped`. Runs ONCE per session by default. On FAIL, the agent fixes and re-runs the FULL packet (not just the failing dimension) up to 3 internal rounds. The agent does NOT return control to the `/arh-implement` orchestrator until either:

- All six dimensions PASS or are accepted-N/A, OR
- Round 3 still has FAILs → agent writes `docs/features/<id>/EVIDENCE-ESCALATION.md` with the round table and returns BLOCKED to the orchestrator.

The orchestrator's Step 2 precondition reads `impl_evidence` from state. If the agent returned BLOCKED, the orchestrator stops cleanly without trying Step 2.

## The six dimensions

Each reads an existing canonical source — no new config (every key is already written by `/arh-init` Phase 4 or `stack-smoke.md`):

| # | Dimension | Source key / file | PASS criterion | N/A trigger |
|---|---|---|---|---|
| 1 | `typecheck`    | `docs/config/project-commands.yaml` `typecheck:` | command exits 0 | key absent or empty |
| 2 | `unit_tests`   | `project-commands.yaml` `test_unit:` (fallback `test:`) | command exits 0 | both keys absent/empty |
| 3 | `lint`         | `project-commands.yaml` `lint:` | command exits 0 | key absent or empty |
| 4 | `runtime`      | `docs/config/stack-smoke.md` `Run:` / `Docker:` per runnable stack | **per stack**: spawn → `/health` returns 200 → boot-log scan finds no `Error\|Exception\|Panic\|FATAL\|fatal`. Dimension PASS = every applicable stack PASS | every stack section is `(n/a — …)` on both Run: and Docker: |
| 5 | `compile`      | `project-commands.yaml` `build:` | command exits 0 | key absent or empty |
| 6 | `design_check` | `project-commands.yaml` `design_check:` | command exits 0 | key absent or empty |

## Procedure (single round)

Run sequentially. Each dimension is independent — never short-circuit on one failing; collect the full report so the engineer / agent sees the whole picture at once.

For each dimension:

1. **Resolve source.** Read the canonical file; extract the command (or stack-smoke section).
2. **Decide applicability.** Applicability is a pure function of what `/arh-init` Phase 4 wrote to `project-commands.yaml` and `stack-smoke.md`. The skill reads only those two files — never any upstream harness config. Bootstrap has already made the stack-identity decision and encoded the result in the canonical configs; do not re-derive it here.
   - Command present + non-empty → **applicable**. Run it.
   - Command absent / empty → **N/A**. Raise an agent flag (see below).
   - For `runtime`: applicability is decided **per stack**, never for the dimension as a whole. Each `stack-smoke.md` section with a non-`(n/a — …)` `Run:` or `Docker:` line is applicable and gets its own spawn + verdict + log (`evidence/runtime-<stack-id>.log`) — one entry per stack in `runtime.stacks[]`, however many stacks (microservices) the project declares. One stack's blocker is NOT a reason to skip another — "no database" excuses the backend section at most; the frontend boot smoke still runs. Dimension status: PASS when every applicable entry is PASS; FAIL if any entry FAILs; N/A only when *every* section is `(n/a — …)`, and the flag must list the per-stack reasons.
   - For `runtime` Docker paths: probe availability fresh (`docker info` exit 0) at packet time. Never carry an "unavailable" claim from an earlier batch or session — availability changes.
   - For `design_check`: applicable only if `project-commands.yaml design_check:` is present and non-empty. Bootstrap fills this key when it detects a frontend-style stack; teams that don't want a design check leave it blank, which surfaces as a flag for the engineer to confirm-N/A at `/arh-human-review`.
3. **Run when applicable.** Capture stdout + stderr to `docs/features/$ARGUMENTS/evidence/<dim>.log`. Use a 300s timeout per dimension (runtime uses the stack-smoke timeouts: 30s boot, 60s migrate, 10s healthcheck — same as the `validation-execution` stack-smoke phase).
4. **Verdict.**
   - Exit code 0 → `status: PASS`. Keep the log file. Record `{exit_code: 0, command, evidence_path, ran_at}`.
   - Exit code ≠ 0 → `status: FAIL`. Keep the log file. Record `{exit_code, command, evidence_path, ran_at}` and the last 500 chars of stderr for the fix-loop input.
   - For `runtime`: even when `/health` returns 200, scan the captured boot log for `Error|Exception|Panic|FATAL|fatal` within the first 10s of stdout. If matched → `status: FAIL` with `boot_log_scan: matched:<pattern>`. Otherwise `boot_log_scan: clean`.
   - For `runtime` on frontend (browser-served) stacks: 200 + clean boot log is **boot-only** evidence — a client-rendered app serves 200 with an empty mount node. When the repo has browser-capable test tooling installed (E2E runner per `project-commands.yaml` / `stack-smoke.md`), additionally load the root route in it and assert the app actually mounted (rendered children beyond the bare root element); capture the runner output (screenshot too if the runner produces one) under `evidence/`. No browser tooling → keep the boot verdict but record `render_check: "unavailable"` on that stack's entry and raise an agent flag so `/arh-human-review` eyeballs the running app.
   - Provisioning a stack's declared dependencies is part of the check: when its `stack-smoke.md` section carries a `Deps:` line (database, queue, cache, …), bring those services up per that line before spawning — run each entry in order; `(external — …)` entries are assumed already running and skipped. A dependency you chose not to start, or a `[NEEDS CLARIFICATION …]` Deps placeholder, is a FAIL (or a "can't fix without config" escalation) — never an N/A. Tear those services back down (`docker compose down` / `kill`) once the boot check completes, so they don't leak past the packet run.

## Internal fix loop (mirrors `/arh-implement` Step 3 — max 3 rounds)

When any dimension is FAIL after a packet run, do NOT return control to the orchestrator. Run the internal fix loop:

For each round (max 3):

1. **Build the failure list** — one row per FAILing dimension:
   ```
   | Dim       | Command            | Exit | Last 500 chars stderr           | Log path |
   |-----------|--------------------|------|---------------------------------|----------|
   | typecheck | mypy src/          |   1  | src/foo.py:42: error: ...       | evidence/typecheck.log |
   | runtime   | uvicorn app:app    |   - | boot log matched 'Exception'    | evidence/runtime-api.log |
   ```
2. **Fix** — apply the smallest code change that resolves each FAIL. One pass — fix all FAILing dimensions together. Honor every cited ADR (G14 — ADR contradictions escalate to the user immediately; do NOT silently rewrite).
3. **Anti-suppression** (HARD constraint — mirrors Step 3 anti-pattern):
   - Don't suppress lint (`# noqa`, `// @ts-ignore`, `eslint-disable` without a reason comment AND engineer-readable justification).
   - Don't relax typecheck (`Any`, `as unknown as T`, blanket `except Exception` to pass a check).
   - Don't comment out failing unit tests or mark them `skip` / `todo`.
   - Don't blank out the runtime error handler or swallow boot-time exceptions to make /health green.
   - Don't lower the design-check threshold to bypass a violation.
   - **Fix the code, not the check.** A fix that weakens the check is rejected — re-run the round.
4. **Re-run the FULL packet** (all six dimensions). Partial reruns are forbidden; staleness across dimensions masks regressions.
5. **Append a round-table row** to `docs/features/$ARGUMENTS/EVIDENCE-ROUNDS.md` (create if absent):
   ```
   | Round | FAILing dims | Action                          | Result            |
   |-------|--------------|---------------------------------|-------------------|
   | 1     | typecheck    | implementation-agent fix pass   | typecheck ✓       |
   | 2     | runtime      | implementation-agent fix pass   | runtime ✓ — clean |
   ```

### Stop conditions

- All dimensions PASS or accepted-N/A → return control to orchestrator with PASS status. Orchestrator proceeds to Step 2.
- Round 3 still has FAILs → write `docs/features/$ARGUMENTS/EVIDENCE-ESCALATION.md` with the round table + per-dimension persistent details. Return BLOCKED to the orchestrator. Do NOT start round 4.
- Agent reports "can't fix without config / spec / ADR change" (e.g., env var missing, dep upgrade needed, ADR contradiction) → escalate to the user mid-loop. The fix loop pauses until the user responds.

## N/A → agent flag (reuses the existing AF mechanism)

When a dimension is N/A, do **not** silently write `status: N/A` and move on. Append a block to `docs/features/$ARGUMENTS/FLAGS.md` (create the file if absent) in the existing format:

```
### AF-<next>: evidence-na · task: n/a · docs/config/project-commands.yaml
<dim> dimension marked N/A — source key absent/empty. <one-line reason>: e.g. "interpreted language, no compile step" or "backend-only project, no frontend stack".
```

`<next>` is the next sequential AF id (highest existing + 1). Set the dimension's `flag_id` in `impl_evidence.checks.<dim>` to that id. The engineer triages every N/A flag at `/arh-human-review` before commit can proceed — `accept` confirms the N/A is legitimate, `reject` means the engineer expected the dimension to run (in which case they fix the config and re-invoke `/arh-implement`).

## State write (mandatory, unconditional)

After the FINAL packet run (the one that either reached PASS-or-N/A across all six dimensions OR exhausted 3 rounds), write to `docs/features/$ARGUMENTS/state.json` at `.impl_evidence`:

```json
{
  "session_ended_at": "<iso8601>",
  "rounds": 1,
  "checks": {
    "typecheck":    {"status": "PASS",  "source": "project-commands.yaml typecheck:", "command": "mypy src/",       "exit_code": 0, "evidence_path": "docs/features/$ARGUMENTS/evidence/typecheck.log",  "flag_id": null,    "ran_at": "<iso8601>"},
    "unit_tests":   {"status": "PASS",  "source": "project-commands.yaml test_unit:", "command": "pytest -q",       "exit_code": 0, "evidence_path": "docs/features/$ARGUMENTS/evidence/unit-tests.log", "flag_id": null,    "ran_at": "<iso8601>"},
    "lint":         {"status": "PASS",  "source": "project-commands.yaml lint:",      "command": "ruff check src/", "exit_code": 0, "evidence_path": "docs/features/$ARGUMENTS/evidence/lint.log",       "flag_id": null,    "ran_at": "<iso8601>"},
    "runtime":      {"status": "PASS",  "source": "stack-smoke.md Run:",              "command": null, "exit_code": null, "evidence_path": null, "flag_id": null, "ran_at": "<iso8601>", "stacks": [
                      {"stack": "api", "status": "PASS", "command": "uvicorn app:app --port 8000", "exit_code": 0, "evidence_path": "docs/features/$ARGUMENTS/evidence/runtime-api.log", "boot_log_scan": "clean"},
                      {"stack": "web", "status": "PASS", "command": "npm run dev -- --port 4200", "exit_code": 0, "evidence_path": "docs/features/$ARGUMENTS/evidence/runtime-web.log", "boot_log_scan": "clean"}
                    ]},
    "compile":      {"status": "N/A",   "source": "project-commands.yaml build:",     "command": null,              "exit_code": null, "evidence_path": null, "flag_id": "AF-09", "ran_at": null},
    "design_check": {"status": "N/A",   "source": "project-commands.yaml design_check:", "command": null,           "exit_code": null, "evidence_path": null, "flag_id": "AF-10", "ran_at": null}
  }
}
```

`rounds` records how many internal fix-loop rounds it took to reach the final state (1 if PASS on the first pass; up to 3; 3 on the escalation path).

## Handover summary (printed before returning control)

```
Evidence packet (docs/features/$ARGUMENTS/evidence/) — rounds: 2
  Typecheck     PASS  typecheck.log    mypy src/ — 0 errors
  Unit tests    PASS  unit-tests.log   pytest -q — 24/24 green
  Lint          PASS  lint.log         ruff check — 0 errors
  Runtime       PASS  runtime-api.log  uvicorn — /health 200, boot log clean
  Compile       N/A   AF-09 raised     interpreted language — please confirm N/A
  Design        N/A   AF-10 raised     no frontend stack declared — please confirm N/A

Status: READY (fixed 1 dimension across 2 rounds). Handing back to /arh-implement → Step 2.
```

On escalation:

```
Status: BLOCKED after 3 rounds. Persistent FAILs:
  Runtime  FAIL  uvicorn — boot log still matches 'Exception' after 3 fix attempts.
                 See EVIDENCE-ESCALATION.md for round table + last logs.
```

## Constraints

- **Never** mark a dimension `PASS` without a real exit-code-0 from a real command. The evidence log file IS the proof; no log → no PASS.
- **Never** state a number you didn't read from captured output. Test counts, pass counts, durations, performance figures, and file/line stats in ANY hand-off (packet summary or prose) must be copied from the corresponding `evidence/*.log` / command stdout. A figure without a captured source is fabrication and invalidates the hand-off.
- **Never** describe an unexecuted check as passing — anywhere, including prose around the packet. Suites that exist in the repo but did not run this session (integration / E2E / performance) are reported as `NOT RUN (runs at /arh-validate-feature)`, never as green.
- **Never** mark a dimension `N/A` without raising the corresponding agent flag.
- **Never** edit `evidence/*.log` files. They are tool stdout/stderr captures and must remain verbatim.
- **Never** rerun a single dimension to "fix" a FAIL without re-running the FULL packet. Partial reruns mask regressions in untouched dimensions.
- **Never** return control to the orchestrator with any dimension still `status: FAIL`. Either fix to PASS, or escalate to BLOCKED with `EVIDENCE-ESCALATION.md`.

## Anti-patterns

- **Don't game N/A.** Applicability is a function of repo-level config (`project-commands.yaml` + `stack-smoke.md`), not story scope. A background-worker change still runs all six dimensions — the runtime check ensures the runnable surface still boots, even if this story didn't touch it.
- **Don't let one stack's excuse cover another.** "No PostgreSQL" N/As the backend's runtime entry at most — the frontend still boots and gets its own verdict. A runtime N/A that names only one stack's blocker while other stacks have runnable `Run:`/`Docker:` lines is a gamed N/A.
- **Don't suppress to pass.** A fix that adds `# noqa`, weakens an assertion, or comments out a failing test is not a fix. Step 3's anti-pattern applies here verbatim.
- **Don't loop past 3.** Round-4 fixes are not allowed. Persistent FAIL means the design needs human eyes; escalate cleanly.
