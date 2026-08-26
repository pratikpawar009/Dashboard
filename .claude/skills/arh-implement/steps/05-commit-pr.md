# Step 5 — Commit + PR

Goal: stage in scope, commit with the project's format, push the feature branch, open a PR with the structured template.

**Always ask the user before commit/push.** This is the first irreversible step. Auto mode does not bypass this confirmation.

## Staging

- Stage **only** files within `docs/features/$ARGUMENTS/PLAN.md` scope plus the test artefacts written by Step 2.
- **Never** `git add -A` or `git add .` — those sweep in unrelated edits, generated artifacts, or secrets.
- Verify with `git status --short` before committing.

## Commit message

Use the project's commit format from `CLAUDE.md`. Default template:

```
<type>(<scope>): <one-line summary>

<body>

Refs: <story-id>
```

`<type>` ∈ `feat|fix|chore|docs|refactor|test|perf|build|ci`.

## Push

Check a remote exists first: `git remote -v`. If empty, STOP after the local commit and report exactly that — `local commit only; no git remote configured — add one and re-run Step 5 to push + open the PR`. Never claim a push or PR happened without one.

`git push -u origin feature/$ARGUMENTS`

Never force-push. Never push to `main` or `master`. Hooks block both anyway; do not try to bypass them.

## PR body template

```
## Story
$ARGUMENTS — <story title>

## What was implemented
- <task 1>
- <task 2>

## Test case results

| TC | Title | Result | Notes |
|----|-------|--------|-------|
| TC-01 | Apply valid promo code | PASS |  |
| TC-03 | Apply expired promo code | PASS | required client-side validation tweak |

Validation rounds: <N>
Environment: <env id, e.g. staging-eu>

## Code review
<verdict + summary line>

## Migration / backout
<if any>

## Links
- Plan: docs/features/$ARGUMENTS/PLAN.md
- Validation: docs/features/$ARGUMENTS/VALIDATION-<DATE>.md
- Review: docs/features/$ARGUMENTS/REVIEW.md
```

Open the PR using the loaded `vcs-<provider>` skill (one of `vcs-github`, `vcs-gitlab`, `vcs-bitbucket`). The skill's `## Operations` section documents the exact command for that provider. Pass the title and the `body.md` path you just wrote.

Reporting honesty: claim "PR created" only from the create command's success output (URL / id) — if the command failed or was skipped, the hand-off says exactly that. Any file/line counts quoted in the PR body or hand-off come from `git diff --stat <base>..HEAD` output, never from memory.

If no `vcs-*` skill is loaded, abort with: `vcs integration not configured — set integrations.vcs in harness.yaml and re-run harness generate`.

## Activity-log trailing commit

The activity log at `docs/activity/activity.jsonl` is written by `harness-activity.mjs`
*after* the session ends — always too late for the feature commit it describes. Left
uncommitted, the audit trail for the session silently vanishes from history.

After the PR is pushed, pick it up in a **separate, trailing commit** — never fold it into the
feature commit (that would violate the scope rule above):

1. Check for a change: `git status --short docs/activity/`.
2. If `docs/activity/activity.jsonl` (or its `.gitattributes`) is modified or new, stage
   **only** those files and commit alone:

   ```
   git add docs/activity/activity.jsonl docs/activity/.gitattributes
   git commit -m "chore: update activity log"
   git push
   ```

3. If nothing under `docs/activity/` changed, skip silently — this is not an error.

Stage the activity log file **only**; do not `git add -A`. Keep this out of the PR body — it
is bookkeeping, not feature content.

## Architecture decisions honored (G14)

Append this section to the PR body listing every decision logged in `DECISIONS.md`:

```
## Architecture decisions honored

- D-01: <one-line title> — implemented in <file:line>
- D-02: <one-line title> — implemented in <file:line>
```

If any decision could not be honored, the gate must have escalated already. PR open with an unaddressed decision contradiction is a review-gate blocker.

## Evidence gate (RC5)

Before commit + push, read `docs/features/$ARGUMENTS/state.json` at `.impl_evidence.checks`. This is the six-dimension packet produced by Step 1b.

| State | Action |
|---|---|
| `impl_evidence` missing entirely | **Refuse** commit + push. Emit: `Cannot commit — no impl_evidence on record. Run /arh-implement Step 1b before merging.` This case means Step 1b was skipped or pre-dates this gate; bypassing requires re-running `/arh-implement`. |
| Any dimension `status: FAIL` | **Refuse** commit + push. Emit the list of failing dimensions with command + last 500 chars of the evidence log. Tell the engineer to fix and re-run `/arh-implement` (Step 1b will produce a fresh packet). |
| Any dimension `status: N/A` with `flag_id` whose `.agent_flags[].status` is still `open` | Hand off to the RC4 agent-flag gate below — the `evidence-na` flag is just another open flag the engineer must triage at `/arh-human-review`. |
| All dimensions `PASS` or `N/A` with their flags triaged (`accept` / `reject` / `defer`) | Proceed to the RC4 agent-flag gate. |

Refusal message template (FAIL case):

```
Cannot commit — implementation evidence shows 1 dimension FAIL:

  runtime    FAIL  uvicorn app:app --port 8000
                   evidence/runtime-api.log (last 500 chars):
                   ...Traceback (most recent call last):
                     File "src/app.py", line 12, in <module>
                       from refund.config import RefundConfig
                   ModuleNotFoundError: No module named 'refund.config'...

Fix the failure and re-run /arh-implement. RC5 will re-evaluate on the next packet.
```

The gate exists because static checks (typecheck / lint) routinely pass on code that crashes at boot. The runtime FAIL above is invisible to `tsc --noEmit`, `ruff`, and `pytest tests/unit/` — they never start the server. Evidence is the receipt that catches this class. There is no `--force` flag; bypassing requires manually editing state, which leaves a git-history trail.

## Agent-flag gate (RC4)

Before commit + push, read `docs/features/$ARGUMENTS/state.json` at `.agent_flags`. Count entries where `status: open`.

| State | Action |
|---|---|
| `open_count == 0` | Proceed to the carry-forward gate below. |
| `open_count >= 1` | **Refuse** commit + push. Emit the list of open flags (flag_id, kind, summary, source) and tell the engineer to run `/arh-human-review $ARGUMENTS`. Do NOT proceed until the engineer triages every flag (`status` becomes `accept`, `reject`, or `defer`). There is no `--force` flag; bypassing requires manually editing state, which leaves a git-history trail. |

Refusal message template:

```
Cannot commit — <N> agent flag(s) awaiting triage:

  AF-02  sensitive-default   — RefundConfig.allow_legacy_signing defaults True  (src/refund/config.py:42)
  AF-04  unusual-shape       — temp_buffer / final_buffer naming suggests copy-paste  (src/refund/dispatch.py:71)

Run:  /arh-human-review $ARGUMENTS
```

The gate exists because flags the agent raised but the human didn't see have shipped real bugs in production. The cost of an unactioned flag is now visible: the PR doesn't merge.

## Carry-forward gate (RC3)

Before commit + push, read `docs/features/$ARGUMENTS/state.json` at `.pending_carry_forward`.

| State | Action |
|---|---|
| Empty | Proceed normally. |
| Non-empty, no `--accept-pending` flag | **Warn** with the list of pending items; ask user to either resolve via `harness carry-forward resolve <id> --evidence <path>` OR pass `--accept-pending <comma-separated-ids>` to acknowledge each. Do NOT proceed silently. |
| Non-empty, `--accept-pending <ids>` covers ALL items | Proceed. Append the pending list + acceptance flag to the PR body `## Carry-forward acknowledged` section. |
| Non-empty, `--accept-pending` partial | Same as no-flag — warn for the unaccepted items. |
| Any item with `kind: finding` tagged compliance | `/arh-security-review` will block at its own step regardless of `--accept-pending`. Surface this case to the user before commit. |

PR body addition when carry-forward exists:

```
## Carry-forward acknowledged

The following items were deferred and explicitly accepted at merge time:

- TC-16-perf-load — manual 50-VU load test deferred (per ADR-7); will be tracked in story PERF-002
- R-03-cache-race — accepted (per ADR-4); revisit in story-019
```

This makes the deferral visible in the PR for human reviewers.

## State write (mandatory, unconditional)

After commit + push succeed (BEFORE Step 6 tracker push), apply per `docs/state/SCHEMA.md § Writer rule`.

**Carry the gate's verdicts forward — never recompute or hardcode them.** `validation` and `review` were already written by the Step 2 Validate ∥ Review gate from the round that went GREEN; copy those literals verbatim. Writing `"passed"` unconditionally would silently upgrade a `partial` validation (GREEN admits `V == PARTIAL`), which is the exact carry-forward signal `/arh-validate-feature` and `/arh-review` read the literal for. Step 5 only ever runs after GREEN, so `validation` is `passed` or `partial` and `review` is `PASS` or `PASS WITH WARNINGS` — `failed` / `BLOCKED` cannot reach this step.

PRIMARY — `docs/features/$ARGUMENTS/state.json` (full record):
```json
{
  "impl": "complete",
  "impl_branch": "feature/$ARGUMENTS",
  "validation": "<passed | partial — as written by the Step 2 gate>",
  "validation_summary": "<DATE> P=<P>/<TOTAL> in <N> round(s)",
  "review": "<PASS | PASS WITH WARNINGS — as written by the Step 2 gate>",
  "decisions_referenced": ["D-01", "D-02"],
  "phase": "review",
  "last_updated": "<iso8601>"
}
```

MIRROR — `docs/state/features.json[$ARGUMENTS]` (B-tier fields only: drop `impl_branch`, `validation_summary`, `decisions_referenced`):
```json
{
  "impl": "complete",
  "validation": "<passed | partial — same literal as PRIMARY>",
  "review": "<PASS | PASS WITH WARNINGS — same literal as PRIMARY>",
  "phase": "review",
  "last_updated": "<iso8601>"
}
```

Status writes run regardless of `provider`; Step 6 writes only the tracker comment key. Status fields MUST be literals — see `docs/state/SCHEMA.md § Field ownership`; data shapes (branch, summary, comment id) belong in dedicated P-tier fields (`impl_branch`, `validation_summary`, `tracker_review_comment`). `/arh-validate-feature` and `/arh-review` gates read these literals.
