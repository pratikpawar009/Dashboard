# Phase 4 — Product Gate

Goal: human-approved checkpoint before plan-implementation. Without explicit approval, `/arh-plan-implementation` cannot run.

## On entry (mandatory)

Before surfacing the checklist, initialise the gate state. `gate` is a **B-tier**
field — write to per-feature state AND mirror to the index per
`docs/state/SCHEMA.md § Writer rule`.

PRIMARY — `docs/features/$ARGUMENTS/state.json`:
```json
{ "gate": "PENDING", "last_updated": "<iso8601>" }
```
MIRROR — `docs/state/features.json[$ARGUMENTS]`:
```json
{ "gate": "PENDING", "last_updated": "<iso8601>" }
```

This guarantees that downstream `phase-preconditions` always sees an explicit gate
value, even if the user never types APPROVE/PENDING/CHANGES. Without this write,
the gate field would be `undefined` and `/arh-plan-implementation` could not reason
about whether the gate has been seen.

## Gate checklist

Surface this checklist to the user as context — one line per item — before asking for the decision.

```
PRODUCT GATE — $ARGUMENTS
────────────────────────────────────────────
Required approvals:

  [ ] PO approves Feature Summary, Functional Requirements, and User Flows
  [ ] Designer approves UI specifications via `DESIGN.md` (when `integrations.design != none`); N/A for backend-only
  [ ] (when research verdict is GO-WITH-CONDITIONS) Every condition from research is addressed
      in `## Addressing Research Conditions` with a concrete mitigation
  [ ] (when research carried open clarifications) Every research-time `[NEEDS CLARIFICATION]`
      either appears in PRD `## Open questions` or is recorded in `## Resolved questions`
  [ ] No-placeholder check passed (zero matches of TBD / TODO / "as appropriate" / etc.
      per Phase 1 forbidden-pattern list)
  [ ] Unresolved `[NEEDS CLARIFICATION]` count ≤ 3 (per `clarification-marker` Hard cap)
  [ ] Test-case coverage audit shows zero uncovered AC/FR/NFR ids
      (`docs/test-cases/$ARGUMENTS.json coverage_audit.uncovered == []`)
  [ ] Every test case has a non-empty `requirement_id` resolving to a real AC, FR, or NFR id
  [ ] BA confirms Edge Cases and Open Questions
  [ ] BA reviews test cases for completeness and automation feasibility
  [ ] All approvals recorded in REQUIREMENTS.md "Approvals" section
```

## Decision

Collect the gate verdict with **`AskUserQuestion`** — never have the user type it out, never auto-answer it. One question, three options:

- **Approve** — gate passed; ok to `/arh-plan-implementation`. → apply "## On APPROVE".
- **Request changes** — PRD needs revision. Ask a follow-up free-text question for the specific changes, then → apply "## On CHANGES".
- **Pending** — keep the PRD in review; do not advance. → apply "## On PENDING".

The product owner answers in their own voice. State literals are unchanged: Approve→`APPROVE`, Request changes→`CHANGES`, Pending→`PENDING`.

## On APPROVE

- Append the Approvals section to `REQUIREMENTS.md` with reviewer name, date, and verdict.
- Update state per writer rule. `gate` + `phase` are both B-tier (mirrored).
  - PRIMARY (`docs/features/$ARGUMENTS/state.json`) AND MIRROR (`docs/state/features.json[$ARGUMENTS]`):
    ```json
    {
      "gate": "APPROVE",
      "phase": "plan-requirements-approved",
      "last_updated": "<iso8601>"
    }
    ```
  The `gate` field is mandatory — `/arh-plan-implementation` Step 0 reads it via the
  phase-preconditions matrix (`gate == "APPROVE"`). Setting only `phase`
  is incomplete and will block the next phase.
- Update tracker subtask with `Status: Approved` (when configured).
- Print `Gate PASSED. Next: /arh-plan-implementation $ARGUMENTS`.
- Return the verdict `APPROVE` to the orchestrator, which runs **Phase 4b — push test cases**.
  Do **not** read `${CLAUDE_SKILL_DIR}/steps/04b-push-test-cases.md` from here: the push is
  capped per invocation, so a second call site pushes up to twice the cap in one pass and defeats
  the checkpoint the cap exists to provide.

## On CHANGES

- Capture the change list at the bottom of `REQUIREMENTS.md` under `## Change requests`.
- Update per writer rule (PRIMARY per-feature + MIRROR index):
  ```json
  {"gate": "CHANGES", "last_updated": "<iso8601>"}
  ```
- Hand back to `product-spec-agent` for a revision pass.
- Re-run Phase 4 after revision.

## On PENDING

- Update per writer rule (PRIMARY per-feature + MIRROR index):
  ```json
  {"gate": "PENDING", "last_updated": "<iso8601>"}
  ```
- Print `Gate PENDING. Run /arh-plan-requirements again or update REQUIREMENTS.md manually before proceeding.`
- Do not advance `phase` field.

## Anti-pattern

Never auto-approve. Auto mode does not bypass this gate. The product owner must approve in their voice.
