---
name: arh-human-review
description: Triage agent-raised flags (sensitive defaults, dead code, etc.) from FLAGS.md before commit-PR; capture accept/reject/defer per flag to state `.agent_flags[]`. Commit-PR gated on zero open flags.
argument-hint: "[story-id]"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Grep Glob AskUserQuestion
---
# /arh-human-review — Triage agent-raised flags

## Why this command exists

The agent ALREADY notices small things while it works — "this default looks risky," "this util's only caller is dead code," "this variable naming suggests copy-paste." It writes those notes inline in its output. Then the user scrolls past them.

By the time commit-PR runs, the notes are buried in the session transcript. Three kinds of bugs ship as a result:

1. **The agent flagged the real cause, nobody read it.** Sensitive default exposed a deprecated path; flag was on screen for 8 seconds two hours ago.
2. **Reviewers can't reconstruct what the agent thought.** Code-review PR comments don't show "AI considered X and decided Y" — that lived in the session.
3. **Audit/compliance has no paper trail.** "Did the team consider risk X?" — the only answer is "scroll the transcript and hope."

`/arh-human-review` fixes this by making flag triage a **gated step**: the agent writes flags to a queue, this skill walks the human through them, and commit-PR refuses to run until every flag has a verdict.

**Input:** `$ARGUMENTS` (story id).

**Precondition:** `docs/features/$ARGUMENTS/FLAGS.md` exists with one or more entries, OR `.agent_flags[]` in `docs/features/$ARGUMENTS/state.json` already has entries with `status: open`.

## What this is NOT

- Not a replacement for `/arh-review` — `/arh-review` is the structured code review of the diff; this is the agent's "I noticed something while writing it" feed.
- Not a replacement for `/decide` — `/decide` records choices the agent made between alternatives. Flags are observations the agent surfaced about choices it already made or about surrounding code.
- Not a replacement for `/arh-clarify` — `/arh-clarify` is for "I can't decide without the PO." Flags are post-decision observations from the agent itself.

Three different paper trails, three different audiences:

| Skill | Question | Paper trail audience |
|---|---|---|
| `/decide` | "I chose X over Y" | future engineers, security review |
| `/arh-clarify` | "I can't decide" | PO |
| `/arh-human-review` | "I noticed something" | committing engineer, PR reviewers |

## Pipeline

```
0. Context  →  1. Triage  →  2. Apply
```

## Phase 0 — Context

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-context.md`

Loads:
- Every entry in `docs/features/$ARGUMENTS/FLAGS.md` (queue from the implementation-agent)
- Every entry in `.agent_flags[]` (in `docs/features/$ARGUMENTS/state.json`) with `status: open`
- Dedupes between the two: queue entries that aren't yet in state get appended with `AF-NN` ids; state entries that are already triaged are skipped
- Each flag carries a `source` pointer (`<file>:<line>`) — Phase 1 reads ±3 lines of surrounding code to show the human in context

## Phase 1 — Triage

Read and follow: `${CLAUDE_SKILL_DIR}/steps/01-triage.md`

Walks the human through each open flag, ONE at a time. For each flag:

1. Show the flag: `AF-NN`, `kind`, `summary`, `source`, surrounding code excerpt, `task_id` it came from.
2. Ask the verdict via `AskUserQuestion` (Accept · Reject · Defer · Skip): `accept` (real concern, fix it now), `reject` (noise — one-line rationale required), `defer` (real but out of scope — promotes to `pending_carry_forward[]`).
3. Capture `decision`, `decided_by` (from `git config user.email`), `decided_at` (now), `rationale` (required for reject/defer; optional for accept).

The agent does NOT pick the verdict. This is the human's job. The skill's role is to FORCE the verdict and capture the answer.

## Phase 2 — Apply

Read and follow: `${CLAUDE_SKILL_DIR}/steps/02-apply.md`

Writes the verdicts to `.agent_flags[]` in `docs/features/$ARGUMENTS/state.json`. For each flag:

- `status: accept` — engineer is expected to make the fix in this same session before commit-PR. State records the decision; the fix lands as part of the existing impl task.
- `status: reject` — flag remains in state with the rationale (audit trail). No code change.
- `status: defer` — promotes the flag to `pending_carry_forward[]` with `kind: finding`; sets `carry_forward_ref` to the new item id. The flag and the carry-forward row stay linked; commit-PR's existing `--accept-pending` gate handles the deferral.

When every flag has `status != open`, the round is done. Truncates the bundled lines from `FLAGS.md` and appends a `<!-- triaged YYYY-MM-DD by <user> -->` footer.

## Commit-PR gate

The commit-pr step refuses to commit while any flag has `status: open`. Engineers who try will see:

```
Cannot commit — 2 agent flags awaiting triage:
  AF-02  sensitive-default   — RefundConfig.allow_legacy_signing defaults True (src/refund/config.py:42)
  AF-04  unusual-shape       — temp_buffer / final_buffer naming suggests copy-paste (src/refund/dispatch.py:71)

Run /arh-human-review $ARGUMENTS to triage.
```

This is the whole point of the system. Without the gate, flags get scrolled past. With it, they get decided on, with a name attached.

## Final summary

```
HUMAN-REVIEW COMPLETE
──────────────────────────────────────
Story:           $ARGUMENTS
Flags triaged:   <count>  (accept=<a>, reject=<r>, defer=<d>)
Open after run:  0
Carry-forward additions: <d> rows (for status=defer)
Next: continue implementation OR /arh-implement Step 5 (commit-PR is no longer gated)
```

## Anti-patterns

- **Auto-verdict** — the skill never picks a verdict for the human. If the human doesn't engage, the flags stay open and commit-PR stays gated. That's the design.
- **Bulk reject** — `/arh-human-review --reject-all` does not exist. Every flag needs a one-line rationale on reject. The friction is the point: a thoughtless reject leaves a paper trail that says "I rejected without explanation."
- **Editing past verdicts** — once a flag is `accept/reject/defer` with a decided_by, the skill does NOT let you change the verdict. New observation → new flag. The audit trail matters more than tidiness.
- **Skipping the gate** — there is no `--force` to bypass commit-pr's open-flag gate. If the human really wants to ship without triaging, they delete the flag from state by hand (visible in git history), with their name on the deletion commit. Cost of bypass = visible.
