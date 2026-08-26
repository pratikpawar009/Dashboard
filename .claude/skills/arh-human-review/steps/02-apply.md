# Phase 2 — Apply

Goal: persist triage verdicts to state, promote deferred flags into carry-forward, and close out `FLAGS.md`.

## Procedure

1. Read `docs/features/$ARGUMENTS/state.json` (per-feature; created at /arh-plan-requirements migration point). Default empty record if file absent (rare — implies /arh-human-review ran out of order).
2. For each `TriageVerdict` from Phase 1:
   - If the flag was newly staged from `FLAGS.md` in Phase 0 (not yet in state), append a new entry to `.agent_flags[]` in `docs/features/$ARGUMENTS/state.json` (P-tier) with the full record (flag_id, kind, summary, source, task_id, raised_at, raised_by) plus the verdict fields.
   - If the flag was already in state with `status: open`, mutate that entry — set `status`, `decision`, `decided_by`, `decided_at`, `rationale`. Do NOT touch `raised_at`, `raised_by`, or the original summary.
   - For `verdict: skip`, leave the entry as `status: open`. No mutation beyond what already exists.
3. For each verdict with `verdict: defer`:
   - Append a new row to `.pending_carry_forward[]` in `docs/features/$ARGUMENTS/state.json` (P-tier):
     ```jsonc
     {
       "item_id":     "<flag_id>-carry",
       "kind":        "finding",
       "reason":      "<rationale from triage>",
       "owner":       "<owner from triage>",
       "added_at":    "<iso8601 now>",
       "added_by":    "human-review/02-apply",
       "resolved_at": null,
       "evidence":    null
     }
     ```
   - Set the flag's `carry_forward_ref` to the new `item_id`. Link goes both ways: anyone reading the flag can find the carry-forward row, and anyone reading carry-forward sees `added_by: human-review/02-apply` and can trace back.
4. Write the updated record back to `docs/features/$ARGUMENTS/state.json`. Preserve every other field unchanged. `agent_flags[]` and `pending_carry_forward[]` are P-tier — no index mirror.
5. Touch `.last_updated` in `docs/features/$ARGUMENTS/state.json` to iso8601 now; mirror to index.

## FLAGS.md cleanup

For every flag that received a non-skip verdict in Phase 1:

- Find its `### AF-NN:` block in `docs/features/$ARGUMENTS/FLAGS.md`.
- Replace the block with: `<!-- AF-NN triaged YYYY-MM-DD by <email> · status=<verdict> -->` (one comment line — keeps the file as an audit trail of what was raised, while signalling that it's done).

If every block in FLAGS.md is now a triage comment, append a final footer:

```
<!-- All flags triaged through round of YYYY-MM-DD. -->
```

Do NOT delete FLAGS.md. The implementation-agent's next session will append new `### AF-NN:` blocks beneath the triaged comments.

## Verification

After write, re-read state and assert:

- Every TriageVerdict with `verdict: accept|reject|defer` has a matching `state[...].agent_flags[]` entry with the same `status`.
- Every `verdict: defer` has both `state[...].agent_flags[i].carry_forward_ref` set AND a `state[...].pending_carry_forward[]` row with the matching `item_id`.
- Count of `state[...].agent_flags[]` entries with `status: open` equals the count of `skip` verdicts from Phase 1.

If any assertion fails, restore state from the pre-write copy and escalate `state write integrity check failed — flags not persisted`. Do NOT half-write.

## Summary output

```
HUMAN-REVIEW COMPLETE
──────────────────────────────────────
Story:                  $ARGUMENTS
Flags reviewed:         <total>
  accept                <count>
  reject                <count>
  defer                 <count>  → <count> new pending_carry_forward rows
  skip                  <count>  → commit-PR remains gated
Open flags remaining:   <skip count>
Last updated:           <iso8601>

{if any skipped:}
Skipped flags still blocking commit-PR:
  AF-02  unusual-shape   src/refund/dispatch.py:71
  AF-05  inconsistency   src/refund/store.py:18

Re-run /arh-human-review $ARGUMENTS when ready.
```

## Failure handling

- **State file corrupted** — back up to `docs/features/$ARGUMENTS/state.json` at `.broken-<iso8601>` and escalate. Do NOT attempt repair.
- **Concurrent write** — if `.last_updated` in `docs/features/$ARGUMENTS/state.json` changed between Phase 0 read and Phase 2 write, escalate `state changed mid-triage — another process wrote to $ARGUMENTS; re-run /arh-human-review`. Most likely a parallel session — the human should reconcile.
