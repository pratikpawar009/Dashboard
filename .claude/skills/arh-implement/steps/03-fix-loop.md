# Step 3 — Validate ∥ Review gate: shared fix loop (max 3 rounds)

Goal: after the **Validate ∥ Review gate** joins, decide GREEN vs. fix. On a hard fail, hand the implementation-agent ONE two-section fix directive built only from hard-fail signals, then **re-run the WHOLE gate**; cap at 3 rounds. **Every validation fix pass still produces at least one regression test.**

## The gate (loop body)

The **Validate ∥ Review gate** dispatches `validation-agent` and `code-review-agent` in a **single message** (two `Task` calls), both **READ-ONLY on the source tree** and reading the **same snapshot** — anchored by a **source-scoped** `git status --porcelain` hash (excludes agent artefacts — see `steps/02-validate.md` § Snapshot). Neither agent mutates code, fixtures, or state during the gate.

**GATE MODE state-write deferral.** In GATE MODE both agents write only their report artefacts (`VALIDATION-<DATE>.md`, `REVIEW.md`; the validation-agent also updates the test-case JSON `last_run`) and RETURN their verdict + carry-forward entries — they do NOT touch `state.json` / `features.json`. The orchestrator is the **single writer** that applies all `state.json` / `features.json` writes AFTER the join. (Standalone invocation of either agent keeps self-writing; the deferral is GATE MODE only.)

## Join verdict

Let **V** = validation verdict ∈ {PASS, PARTIAL, FAIL}, **R** = review verdict ∈ {PASS, PASS WITH WARNINGS, BLOCKED}.

**GREEN → proceed to commit:** `V ∈ {PASS, PARTIAL}` and `R ∈ {PASS, PASS WITH WARNINGS}`.

- PARTIAL and PASS WITH WARNINGS are **proceed-with-carry-forward** states, **NOT** fix-loop triggers. Their carry-forward entries flow to the PR body / commit gate, never to a fix pass.

**The fix pass fires ONLY on `V==FAIL` or `R==BLOCKED`.** Everything else is GREEN.

## Round procedure

For each round, build ONE two-section fix directive from the joined reports — the fold is **validation bug-blocks (when `V==FAIL`) ⊕ review CRITICAL + HIGH findings ONLY (when `R==BLOCKED`)**. Populate only the section whose signal fired.

### Section A — Validation failures  (include ONLY when `V==FAIL`)

Source: the validation report's `## Failed (bug blocks)` + `### Errored` sections + every task-completion row marked **MISSING** in `## Task completion verification`.

Each entry carries: TC id, steps executed, expected vs actual, screenshot / artefact path (if produced), failure reason.

Discipline — unchanged from the validation-only loop:

1. **Root cause first.** Apply the `root-cause-first` skill per failure — state `<cause> produces <symptom> because <mechanism>` before any fix; symptom-patching is rejected. Multi-component / deep-stack failures follow the instrumentation + backward-trace techniques in that skill.
2. **Regression-test requirement (G4)** — for every fixed failure, the agent must add or extend a test case:
   - New TCs use id `<STORY>-TC-<NN>` and tag `regression-<original-TC-id>` (e.g. tag `regression-TC-03` when fixing TC-03).
   - When extending an existing TC, document the new boundary in `then:` and add tag `regression-<original-TC-id>`.
   - Append the new/updated TC to `docs/test-cases/$ARGUMENTS.json` per the `test-case-generation` schema.
   - Re-run `coverage_audit` after appending; `uncovered` must remain `[]`.
   - A fix without a corresponding regression-tagged TC is rejected — re-run the fix pass.
3. **No test mutation** — see the Anti-pattern section: fix the code, not the tests.

### Section B — Review blockers  (include ONLY when `R==BLOCKED`)

Source: the review report's **CRITICAL** and **HIGH** findings ONLY — each fed to the agent with its `Source:` line (DECISIONS.md entry, PLAN task, or rule file) so the fix targets the cited contract.

**MEDIUM/LOW findings are PR-body warnings, never a fix trigger.** They flow to the PR body as warnings and never enter the directive.

**G14 — ADR-contradiction pause.** Any `adr-violation` finding — and any proposed validation fix that contradicts a cited ADR / DECISIONS.md entry — is **never** a silent code change. Pause the loop and escalate with options: re-scope the story, write a superseding DECISIONS.md entry, or pause the branch for human review. The loop resumes only after the user responds.

### Fix pass — runs ALONE

Invoke `implementation-agent` ONCE with the folded directive (Section A ⊕ Section B — whichever fired; fix all listed failures in the one pass). The fix pass runs **alone** between rounds — no `validation-agent` and no `code-review-agent` run alongside it. Each fix targets the stated root cause / cited `Source:`.

### Re-run the WHOLE gate

After the agent reports done, **re-dispatch the whole Validate ∥ Review gate** — both `validation-agent` AND `code-review-agent`, again in a single message on the fresh **source-scoped** snapshot (`steps/02-validate.md` § Snapshot). **Not validation-only:** a validation fix can introduce a review blocker and a review fix can break a flow, so both V and R must be re-earned every round. Join, re-apply the GREEN test, then append a row to the round table.

## Round table

```
| Round | V    | R       | Fix directive                       | Action                        | Result                  |
|-------|------|---------|-------------------------------------|-------------------------------|-------------------------|
| 1     | FAIL | BLOCKED | A: TC-03,07  ⊕  B: F-1 (CRITICAL)   | implementation-agent fix pass | V=FAIL ⨯, R=PASS ✓      |
| 2     | FAIL | PASS    | A: TC-07                            | implementation-agent fix pass | V=PASS ✓, R=PASS ✓ → GREEN |
```

## Caps & escalation

Two counters, both incremented per round:

- **Review sub-cap.** Escalate after the 2nd BLOCKED review round — `review_blocked_rounds >= 2` → write `docs/features/$ARGUMENTS/REVIEW-ESCALATION.md` with the unresolved CRITICAL/HIGH findings and ask the user to re-scope, accept via a superseding DECISIONS.md entry, or pause the branch for human review. An architectural blocker rarely resolves via more fix passes.
- **Combined hard cap = 3 rounds.** Still not GREEN after round 3 → **stop, and question the architecture — do not start round 4.** Per `root-cause-first` § "question the architecture": three failed fixes signal a wrong design, not a closer next fix. Write `docs/features/$ARGUMENTS/ESCALATION.md` framed as a DESIGN question — "is the PLAN / cited ADR sound, or are we patching symptoms?" — with the round table and per-round root-cause notes. Escalate to the user for an architecture decision, not another fix attempt.
- Implementation-agent reports the failure cannot be fixed without changing the spec → stop and escalate to the user; the design may be wrong.

## Anti-pattern

Never touch test fixtures, test-case JSON, or test assertions to make a failing flow pass. Fix the code, not the tests. Never reduce test coverage, weaken assertions, mark a test `skip` / `todo`, or change the AC to make a flow pass. If a flow is genuinely broken because the AC is wrong, escalate to update the story; do not silently mutate the test.
