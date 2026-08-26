# Phase 0 — Context

Goal: assemble the list of open flags Phase 1 will triage.

## Procedure

1. Resolve `docs/features/$ARGUMENTS/`. Missing → escalate `feature folder not found`.
2. Read `docs/features/$ARGUMENTS/FLAGS.md` if present. Parse one entry per line block, in the format described in the implementation-agent's "On observation" branch:

   ```
   ### AF-<next>: <kind> · task: T-NN · <source-file>:<line>
   <one-line summary>
   <optional second-line context>
   ```

   Entries with a `### AF-NN:` heading whose `AF-NN` is already in state with `status != open` are SKIPPED (already triaged).
3. Read `docs/features/$ARGUMENTS/state.json` at `.agent_flags` (default `[]`).
4. Build the working set:
   - State entries with `status: open` → include.
   - FLAGS.md entries not yet in state → assign next `AF-NN` (zero-padded, sequence within feature, not global) and stage them for write in Phase 2.
   - State entries with `status: accept|reject|defer` → skip (already done).
5. For each flag in the working set, read ±3 lines around `source` (the `<file>:<line>` pointer). If the file or line no longer exists (refactored since the flag was raised), mark the flag as `drift` and surface in Phase 1 with a special prompt; Phase 1 still accepts a verdict but defaults to `reject` (the original concern may no longer apply).

## Sort order

Within the working set, sort by `kind`-priority then `raised_at`:

| Priority | Kind |
|---|---|
| 1 | `sensitive-default` (security blast radius likely highest) |
| 2 | `risky-pattern` |
| 3 | `dead-code` |
| 4 | `inconsistency` |
| 5 | `unusual-shape` |
| 6 | `other` |

Higher-priority kinds get triaged first — if the human aborts mid-triage, the most important flags are at least addressed.

## Output

A list of `Flag` records ready for Phase 1:

```jsonc
{
  "flag_id":   "AF-03",
  "kind":      "sensitive-default",
  "summary":   "RefundConfig.allow_legacy_signing defaults to True; exposes SHA-1 path deprecated by ADR-0017",
  "source":    "src/refund/config.py:42",
  "task_id":   "T-04",
  "raised_at": "<iso8601>",
  "raised_by": "implementation-agent",
  "excerpt":   "<±3 lines of code around src/refund/config.py:42>",
  "drift":     false
}
```

## Empty-set behaviour

If the working set is empty (no FLAGS.md AND no `status: open` rows in state):

```
No open agent flags for $ARGUMENTS. Nothing to triage.
```

Exit zero. Do NOT proceed to Phase 1.

## Git identity

Read `git config user.email` (fall back to `git config user.name`). Phase 1 uses this for `decided_by`. If neither is set, escalate `git identity not configured — set user.email before running /arh-human-review` (audit trail is not optional).
