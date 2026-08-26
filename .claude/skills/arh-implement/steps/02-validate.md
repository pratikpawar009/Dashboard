# Step 2 — Validate ∥ Review gate (mandatory)

Goal: Step 2 **is** the unified **Validate ∥ Review gate** — a bounded fix loop that runs
validation and code review together against one working-tree snapshot and only lets a GREEN
result through to commit. It is not a lone validate step.

**This gate is non-negotiable.** Even if the implementation-agent reports all local checks pass,
you MUST run it. Unit tests do not catch integration regressions; mocked tests do not match
production; and a diff can pass every test while violating an ADR or a project rule. Skipping this
gate is the most common cause of regressions and architectural drift reaching `main`.

## Structure

```
# ── one-time entry gate (before the loop) ──────────────────────────────
assert state.json .impl_evidence exists and every check is PASS-or-N/A     # Step 1's receipt
assert docs/test-cases/$ARGUMENTS.json exists

round = 0
review_blocked_rounds = 0
discards = 0

loop:                                                                       # combined hard cap = 3
    run PRE-FLIGHT checks                                                   # PER ROUND — a fix pass can break the build/env
    snapshot = hash(SOURCE tree)                                            # SOURCE only (see Snapshot) — the consistency anchor

    # single message, two Task calls, both READ-ONLY on the source tree.
    # The directive is the RUNTIME SIGNAL that selects each agent's report-only branch.
    V = dispatch(validation-agent, $ARGUMENTS, directive="GATE MODE — report-only")   # RETURN verdict + carry-forward
    R = dispatch(code-review-agent, $ARGUMENTS, directive="GATE MODE — report-only")   # RETURN verdict + carry-forward

    if hash(SOURCE tree) != snapshot:                                       # a stray write raced the read-only agents
        discards += 1                                                        # NOT a gate round — no fix ran, nothing was judged
        if discards >= 2: escalate "source tree keeps changing mid-gate"     # bounded: never spin
        continue                                                             # re-run on a fresh snapshot; `round` unchanged

    discards = 0                                                            # the guard held — only CONSECUTIVE discards escalate
    round += 1                                                              # counted only once a joined verdict exists
    apply_state_writes(V, R)                                                 # orchestrator = single writer, AFTER the join

    if V ∈ {PASS, PARTIAL} and R ∈ {PASS, PASS WITH WARNINGS}:               # trinary GREEN
        goto Step 5 (commit)

    if R == BLOCKED: review_blocked_rounds += 1
    if review_blocked_rounds >= 2: write REVIEW-ESCALATION.md; escalate      # review sub-cap
    if round >= 3:                 write ESCALATION.md;        escalate      # combined hard cap

    fix_pass(V, R)                                                           # steps/03-fix-loop.md
    # loop
```

## One-time entry gate (before the loop)

These are entry preconditions, checked **once** before round 1 — they gate Step 1's hand-off, not
each round.

| Check | Failure → |
|---|---|
| `docs/features/$ARGUMENTS/state.json` `.impl_evidence` exists with `checks` populated | escalate: `Step 1 returned without its mandatory state write — re-invoke implementation-agent to complete the evidence pass + state write. Prose hand-off alone is not acceptance.` |
| Every `.impl_evidence.checks.*.status` is `PASS` or `N/A` (N/A rows carry a `flag_id`) | escalate listing the offending dimensions: `Step 1 handed over non-green evidence — the agent must fix or escalate via EVIDENCE-ESCALATION.md, never hand over FAILs` |
| `docs/test-cases/$ARGUMENTS.json` exists | escalate: `Run /arh-plan-requirements $ARGUMENTS first` |

## Environment PRE-FLIGHT checks (PER ROUND, before each dispatch)

Run these **at the top of every round**, before the validation-agent / code-review-agent dispatch —
not once. A fix pass (`steps/03-fix-loop.md`) can break the build or the environment, so the
snapshot the agents validate must be re-proven bootable each round. The current serial fix-loop
already re-runs pre-flight every round via "Step 2 procedure"; the gate preserves that.

| Check | Failure → |
|---|---|
| Required env vars set (per `harness.yaml`) | escalate with the missing var names |
| Endpoint / dev server reachable | escalate: `Cannot reach <url>; aborting validation` |
| Mobile device / simulator available (mobile role) | escalate: `Connect a device or start a simulator` |
| App build does not boot | escalate with the build error |

Do not "mock your way out" of any of these. Escalate.

## Round procedure

1. **Pre-flight** — run the PER-ROUND table above. Any failure escalates; do not dispatch.
2. **Snapshot (SOURCE only)** — compute a hash of the **source tree** the agents review: the
   implementation diff (`git status --porcelain` / `git diff main...HEAD` **filtered to source**).
   **Exclude the agents' own expected outputs** — the `VALIDATION-<date>.md` / `REVIEW.md` reports
   under `docs/features/`, the `docs/test-cases/$ARGUMENTS.json` `last_run` fields the
   `validation-agent` rewrites every run, any generated flow files, and `state.json` / `features.json`
   (the orchestrator writes those post-join). Those are agent artefacts, not source; a raw
   `git status --porcelain` hash would include them and trip the join guard every round
   (non-convergence). The anchor's job is only to prove both agents saw the **same source** and that
   no fix mutated source mid-round. Concretely: `git status --porcelain -- . ':(exclude)docs/features'
   ':(exclude)docs/test-cases' ':(exclude)docs/state'` (add the generated-flow dir if your stack
   writes one).
3. **Dispatch (single message, two `Task` calls, with the GATE-MODE directive)** — the orchestrator
   dispatches `validation-agent` **and** `code-review-agent` in a **single message** (two `Task`
   calls), both **READ-ONLY** on the source tree. It **MUST** pass an explicit
   **`GATE MODE — report-only`** directive in each agent's Task prompt (not merely invoke them). This
   directive is the **runtime signal** that selects the deferral branch of each agent's
   mode-conditional state-write contract (`review-assessment` / `validation-execution`); without it
   the agents fall back to self-writing `state.json` and the concurrent read-modify-write race
   reopens. They run concurrently against the one source snapshot; neither edits source.
   - `validation-agent` returns V ∈ `{PASS, PARTIAL, FAIL}` — see `validation-execution`.
   - `code-review-agent` returns R ∈ `{PASS, PASS WITH WARNINGS, BLOCKED}` — see `steps/04-review.md`
     for the full review-agent verdict contract.
4. **Join guard** — recompute the **SOURCE** hash (same exclusions). If it differs from the snapshot
   (a stray write raced the read-only agents), discard the dispatch and re-run on a fresh snapshot —
   a combined verdict across two different source trees is not valid. A discard is **not** a gate
   round: no fix pass ran and neither verdict was judged, so `round` does **not** advance and an
   unrelated file touch can never burn one of the three fix rounds. Bound it — on a **second**
   consecutive discard, stop and escalate `source tree keeps changing mid-gate` rather than
   re-dispatching forever; something outside the gate is writing to source (a watcher, a formatter,
   another session). The agents' report / test-case-JSON writes are excluded, so they never trip this
   guard.
5. **State write (orchestrator = single writer)** — apply all state after the join. See below.
6. **Evaluate the trinary** — GREEN or fix pass. See below.

## GATE MODE — state-write deferral

The orchestrator passes a **`GATE MODE — report-only`** directive to each agent (see Round
procedure step 3) — that directive is what puts them in GATE MODE. In GATE MODE each agent writes
its **report file** — `VALIDATION-<YYYYMMDD-HHMM>.md` / `REVIEW.md` — and the `validation-agent`
additionally rewrites the `docs/test-cases/$ARGUMENTS.json` `last_run` fields (its normal Phase-4
output, excluded from the source snapshot). Neither agent touches `state.json` or `features.json`;
both **RETURN** their verdict + carry-forward entries instead. The orchestrator is the **single
writer** that applies all `state.json` / `features.json` writes **AFTER the join**, so two concurrent
agents can never interleave a write or clobber each other:

```jsonc
// docs/features/$ARGUMENTS/state.json  (PRIMARY — full record)
{
  "validation": "<passed | partial | failed>",
  "validation_summary": "<DATE> P=<P>/<TOTAL> in <round> round(s)",
  "review": "<PASS | PASS WITH WARNINGS | BLOCKED>",
  "review_report": "docs/features/$ARGUMENTS/REVIEW.md",
  "phase": "review",
  "pending_carry_forward": [ /* any entries the two agents RETURNED, appended here — never by the agents */ ]
}
// docs/state/features.json[$ARGUMENTS]  (MIRROR — B-tier status literals only)
```

(Standalone invocation of either agent — `/arh-validate-feature`, `/arh-review` — keeps
self-writing its own state; the deferral applies only when they run inside this gate.)

## Trinary GREEN → commit

GREEN is a **trinary AND on the same snapshot**:

> **`V ∈ {PASS, PARTIAL}` and `R ∈ {PASS, PASS WITH WARNINGS}`** → go to **Step 5 (commit)**.

`PARTIAL` and `PASS WITH WARNINGS` are **proceed-with-carry-forward** states, **NOT** fix-loop
triggers: the orchestrator records their carry-forward entries in `.pending_carry_forward` and flags
them in the PR body, then proceeds. They do not spin another round.

## Fix pass → only on V==FAIL or R==BLOCKED

The fix pass fires **ONLY** on **`V==FAIL`** or **`R==BLOCKED`**. Build one folded fix directive and
hand it to `steps/03-fix-loop.md`:

> **fix directive = validation bug-blocks (when `V==FAIL`) ⊕ review `CRITICAL` + `HIGH` findings ONLY
> (when `R==BLOCKED`)**

`MEDIUM`/`LOW` review findings are **PR-body warnings, never a fix trigger** — they ride along as
carry-forward, exactly like `PARTIAL` / `PASS WITH WARNINGS`.

The fix pass runs under `steps/03-fix-loop.md`: `root-cause-first` per failure
(`<cause> produces <symptom> because <mechanism>`), the **G4** regression-test-per-failure
requirement, and the **G14** ADR-contradiction pause all apply unchanged. After the fix pass returns,
loop back to the top of the round procedure (pre-flight re-runs).

## Caps and escalation

| Cap | Trigger | Action |
|---|---|---|
| Review sub-cap | `review_blocked_rounds >= 2` (2nd `BLOCKED` round) | Stop. Write `docs/features/$ARGUMENTS/REVIEW-ESCALATION.md` with the unresolved `CRITICAL`/`HIGH` findings; escalate per `steps/04-review.md` (re-scope / accept-with-ADR / pause). Re-implementation does not fix an architectural defect. |
| Combined hard cap | `round >= 3` (3 rounds elapsed) | Stop — do not start round 4. Write `docs/features/$ARGUMENTS/ESCALATION.md` framed as a DESIGN question per `root-cause-first` § "question the architecture"; escalate to the user for an architecture decision, not another fix attempt. |

Never proceed to commit while any `CRITICAL` review finding or any validation `FAIL` remains.

## Output

```
Validate ∥ Review gate — round <round>/3   snapshot <porcelain-hash>
  Validation (V):  PARTIAL   4/5 passed   (report: docs/features/$ARGUMENTS/VALIDATION-<DATE>.md)
      ✓ TC-01  Apply valid promo code
      ⨯ TC-03  Apply expired promo code   → carry-forward (PARTIAL, not a fix trigger)
  Review     (R):  PASS WITH WARNINGS      (report: docs/features/$ARGUMENTS/REVIEW.md)
      2 MEDIUM findings → PR-body warnings

  Verdict: GREEN — V ∈ {PASS, PARTIAL} and R ∈ {PASS, PASS WITH WARNINGS}. Proceed to Step 5.
```

On GREEN, continue to Step 5 (commit + PR). On `V==FAIL` or `R==BLOCKED`, enter the fix pass
(`steps/03-fix-loop.md`) and loop, subject to the caps above.
