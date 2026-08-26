# Step 1 — Implement tasks

Goal: convert the feature's tasks (the `tasks.json` DAG) into code, dispatching file-disjoint tasks to concurrent `implementation-agent` workers with local checks per task. The orchestrator records each task's status into `tasks.json` as workers return, so the implementation can resume (`--resume`) after interrupt.

## Procedure — DAG scheduler (parallel)

The orchestrator (this step, main session) drives the task DAG; single-task `implementation-agent` workers run **concurrently**. Race-free by the same rule as `/arh-intake`: workers only edit their own task's `files[]` and **return** everything else; the orchestrator is the sole writer of every shared artifact (`tasks.json`, `QUESTIONS.md`, `FLAGS.md`) and the sole merger into the working tree. **No git commit happens here — Step 5 remains the only, gated, post-validation commit owner.**

1. Read `docs/features/$ARGUMENTS/tasks.json` (`tasks` DAG + `file_plan`). Start from the resume point set by Step 0 (skip `done` tasks). PLAN.md carries the decisions/ADRs workers must honor.
2. **Schedule loop** — repeat until every task is `done | blocked | skipped`:
   1. **Ready set** = `pending` tasks whose `predecessors` are all `done`. Never re-select a task already `done | blocked | skipped`.
   2. **Batch** = a maximal subset of the ready set that is pairwise **file-disjoint** — their `files[]`, resolved via `file_plan`, must not overlap. Cap the batch at **4** concurrent tasks.
   3. **Dispatch concurrently**: one `implementation-agent` per batch task, all in a **single message** (multiple `Task` calls), each passed its `TASK_ID`. Each worker implements only its task (steps 1–4 of its procedure) and **returns** a result payload (status, files_touched, reason, queued questions, queued flags) — it does **not** write `tasks.json`, `QUESTIONS.md`, or `FLAGS.md`. If `Task` is unavailable, run the batch sequentially instead; never skip tasks.
   4. **Record (serial, orchestrator-owned)**: as results return, the orchestrator — the single writer — (a) writes each task's `status`/`completed_at`/`files_touched`/`reason` into `tasks.json` `tasks[TASK_ID]` (the G2 `--resume` persistence; replaces the old `state.json .impl_tasks[]`, and `state.json` keeps only the `tasks.file` pointer); (b) appends each returned question to `QUESTIONS.md` and each returned flag to `FLAGS.md`, assigning monotonic `AF-NN` ids here. One writer → no interleave-loss and no `AF-NN` id collision across parallel workers.
   5. **Merge in `T-NN` order**: workers touch disjoint files, so the orchestrator folds their diffs into the working tree in ascending id order for a deterministic, reviewable tree. This is a working-tree merge only — nothing is committed to history (Step 5 owns that).
   6. A `blocked` task leaves its dependents unready; independent branches keep running. Recompute the ready set and loop — unless the new ready set is empty while tasks are still `pending`, which is step 7.
   7. **Empty ready set with tasks still `pending` — resolve it, never loop on it.** A `pending` task whose predecessor is `blocked` or `skipped` can never become ready: that predecessor will never reach `done`, so the loop's exit condition (every task `done | blocked | skipped`) is unreachable and re-looping spins forever. The moment the ready set comes back empty with any task still `pending`:
      1. **Cascade the block.** For every `pending` task with a `blocked | skipped` predecessor, write `status: blocked` and `reason: "predecessor <T-NN> blocked"` into `tasks.json`. Repeat until no `pending` task has a non-`done` predecessor — a block propagates transitively down its entire dependent subtree, not just one level.
      2. **Anything still `pending` after the cascade is a cycle.** A task whose predecessors are all `done` would have been in the ready set, so a survivor of the cascade sits in a `predecessors` cycle that `plan-validation` § Cross-section consistency should have rejected. Stop; do not cascade it to `blocked` (it is a plan defect, not a blocked dependency). Escalate: `tasks.json cycle — <T-NN> → … → <T-NN> never becomes ready; fix the DAG and re-run /arh-plan-implementation`.
      3. Every task is now `done | blocked | skipped`, so the loop exits.
3. When the DAG is drained, proceed to the clarification check below.

**Why file-disjoint batching:** two tasks editing the same file cannot run concurrently (plan-validation already rejected unordered same-file tasks). A non-file conflict (shared DB/port) was serialized at plan time by a `predecessors` edge, so it never lands in the same ready set.

## Constraints

- **Never** push, amend, or open a PR in this step. Step 5 owns commit/PR.
- **Never** edit files outside the PLAN.md scope without asking the user.
- **Never** introduce a feature flag or backwards-compat shim that was not in PLAN.md.
- **Never** suppress lint or typecheck output ("// @ts-ignore" without comment, `# noqa` without reason).
- **Never** improve adjacent code, fix unrelated bugs, or reformat untouched regions. See the `surgical-changes` rule.
- **Always** carry-forward unrelated issues to the PR body `## Carry-forward` section; never inline-fix them.
- **Never** stop a task to ping the PO for one ambiguity. Workers **return** mid-stream questions in their result; the orchestrator appends them to `docs/features/$ARGUMENTS/QUESTIONS.md` (single writer) and the end-of-session `/arh-clarify` bundles them.
- **Never** bury an observation in chat output. Workers **return** mid-stream observations as flags; the orchestrator appends them to `docs/features/$ARGUMENTS/FLAGS.md` and assigns `AF-NN` ids (single writer), and the end-of-session `/arh-human-review` walks the engineer through them.

## End-of-session clarification round

When the agent finishes (every task done, OR a task is `blocked`, OR the session is being suspended), check `docs/features/$ARGUMENTS/QUESTIONS.md`:

- File missing OR empty (only comments / blank lines) → no clarification round needed. Continue to the evidence pass below.
- File has ≥1 question line → invoke `/arh-clarify $ARGUMENTS`. This bundles every queued question into one PO-facing round and posts a single tracker comment. The orchestrator does NOT proceed to Step 2 (the Validate ∥ Review gate) until the PO answers and the engineer runs `/arh-clarify $ARGUMENTS --apply`. Status update on hand-off: `BLOCKED on CLARIFY-<round>.md — <N> questions awaiting PO`.

This replaces the anti-pattern of N tracker-pings per session and the worse anti-pattern of silent guesses.

## End-of-session evidence pass (handover receipt)

After the clarification check, and only once the whole DAG is drained, the orchestrator invokes `implementation-agent` **once in evidence mode** (`--evidence`, no `TASK_ID`) to run the six-dimension evidence pass over the whole feature per the `evidence-pass` skill — full procedure, the max 3 rounds internal fix loop, state-record shape, and anti-suppression rules all live in `evidence-pass` skill. It runs exactly once (never per parallel worker), so the packet reflects the merged result of every task.

- **READY** (all six dimensions PASS or accepted-N/A) → continue to flag triage below.
- **BLOCKED** (round-3 escalation) → `evidence-pass` writes `EVIDENCE-ESCALATION.md` and the final FAIL `impl_evidence`; stop.

State write (`.impl_evidence`, P-tier) happens inside `evidence-pass`. Step 2's precondition reads `impl_evidence` from state; on BLOCKED it refuses to start, and the same record blocks Step 5 (commit-PR) via RC5. Gates are agnostic to where the evidence ran — they only read state.

## End-of-session flag triage

After the evidence pass has written its receipt (so FLAGS.md contains both the implementation-agent's Step 2 "On observation" entries AND any `evidence-na` blocks the evidence pass just appended), check `docs/features/$ARGUMENTS/FLAGS.md`:

- File missing OR every block is a `<!-- ... triaged ... -->` comment → no triage round needed. Continue to Step 2.
- File has ≥1 `### AF-NN:` block that is NOT yet triaged → prompt the engineer: `<N> agent flags raised this session. Run /arh-human-review $ARGUMENTS to triage before commit-PR? [y/N]`. On `y`, invoke `/arh-human-review $ARGUMENTS`. On `n`, continue to Step 2 — but Step 5 (commit-PR) will refuse to run while flags remain `status: open`, so the engineer will be forced to triage eventually.

This is the second of two "did you see what the agent saw?" gates. Clarifications surface things the agent COULD NOT decide; flags surface things the agent DECIDED but wants the engineer to know about. The check must run AFTER the evidence pass so that `evidence-na` flags raised for N/A dimensions are visible to the prompt — running it earlier means those flags exist on disk but never get offered for triage, and the engineer discovers them only when a downstream gate blocks.

## Output

```
Implementation: <N>/<N> tasks
  ✓ task-01  Add /promo-codes endpoint        (lint clean, types clean, unit tests green)
  ✓ task-02  Wire endpoint into checkout flow ...
  ⨯ task-04  Edge case in promo expiry        (blocked: missing fixture; see report)

Evidence packet (docs/features/$ARGUMENTS/evidence/) — rounds: 1
  Typecheck     PASS  typecheck.log    mypy src/ — 0 errors
  Unit tests    PASS  unit-tests.log   pytest -q — 24/24 green
  Lint          PASS  lint.log         ruff check — 0 errors
  Runtime       PASS  runtime-api.log  uvicorn — /health 200, boot log clean
  Compile       N/A   AF-09 raised     interpreted language — please confirm N/A
  Design        N/A   AF-10 raised     no frontend stack declared — please confirm N/A

Status: READY. Handing back to /arh-implement → Step 2.
```

If any task is `blocked`, surface the reason and ask the user before running the evidence pass.

If the evidence pass returns BLOCKED after 3 rounds, surface `EVIDENCE-ESCALATION.md` and stop. The orchestrator's Step 2 precondition will refuse to start; do not try to bypass.
