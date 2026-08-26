# Step 2 — Fix

Goal: patch the stated root cause, nothing more.

## Procedure

Invoke `implementation-agent` with:

- the defect description + the **root cause** stated in Step 1,
- the bounded scope (files / functions) from Step 1,
- the instruction: fix the cause, single change, no adjacent work.

The agent:

- Obeys the `surgical-changes` rule — touches only what the root cause requires. No opportunistic refactors, no "while I'm here" cleanups, no reformatting untouched regions. Unrelated findings it notices go to `docs/features/<id>/FLAGS.md` (when `--for <id>`) or are reported in the hand-off, never inline-fixed.
- Honours every cited ADR. A fix that would contradict an ADR is **escalation** — it should have bounced in Step 1; if it surfaces here, stop and route to `/arh-intake`.
- When the touched file is UI: binds tokens / follows `<framework>-patterns` conventions, AND runs the `design-binding` screen-fidelity diff (loaded by the implementation-agent when a design provider is configured) — but **scoped to the elements this fix changes**. Verify the patched region matches the design artifact; do NOT flag pre-existing design gaps unrelated to the root cause — that breaches surgical scope and belongs to `/arh-implement` or a separate fix.

## Constraints

- One root cause → one fix. If the fix balloons beyond the Step 1 scope, STOP — the defect was mis-classified; re-run Step 1's architectural-bounce check.
- Never weaken a test, assertion, or AC to make a flow pass (the regression test in Step 3 must be a real guard).
- Never push, amend, or open a PR here — Step 4 owns that, behind the human gate.

## Output

`Fixed: <root cause>. Files touched: <list>. Within Step 1 scope: yes/no (if no → bounce).`
