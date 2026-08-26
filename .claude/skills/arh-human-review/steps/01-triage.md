# Phase 1 — Triage

Goal: collect a verdict for each open flag, one at a time, with the human in the loop.

## Procedure

For each flag in the working set (sorted by kind-priority from Phase 0):

1. Present the flag block:

   ```
   ──────────────────────────────────────
   AF-03  (sensitive-default)            [1 of 3]
   ──────────────────────────────────────
   Raised by: implementation-agent
   Raised at: 2026-05-21 13:42 UTC
   Task:      T-04
   Source:    src/refund/config.py:42

   Summary:
     RefundConfig.allow_legacy_signing defaults to True;
     exposes SHA-1 signing path deprecated by ADR-0017.

   Code:
     39 │ class RefundConfig:
     40 │     timeout_s: float = 30.0
     41 │     retry_count: int = 5
     42 │     allow_legacy_signing: bool = True       ◄── flag here
     43 │     signature_algo: str = "sha256"
     44 │     dead_letter_table: str = "webhook_dlq"
   ```

   For `drift: true` flags, replace `Code:` with `(source no longer at recorded line — file refactored since raised; verdict default = reject)`.

2. Collect the verdict with **`AskUserQuestion`** (not a typed letter) — one question per flag, four options: **Accept · Reject · Defer · Skip**. The human picks; the agent never self-answers.

   - `accept` — concern is real; engineer will fix in this session.
   - `reject` — concern is noise; one-line rationale required.
   - `defer` — concern is real but out of scope; promotes to `pending_carry_forward[]` with one-line rationale.
   - `skip` — leaves the flag `open` and moves to the next. Commit-PR remains gated. Use only when the human needs to look something up before deciding.

3. On `accept`:
   - Prompt: `Decision (one line, what you'll do):` — captured into `decision`.
   - Prompt: `Rationale (optional, why):` — captured into `rationale` (may be empty).
   - The skill does NOT make the code fix — the engineer is expected to fix it before commit-PR. The verdict records the commitment; the gate enforces it.

4. On `reject`:
   - Prompt: `Rationale (required, why this is noise):` — captured into `rationale`. Refuse an empty rationale; re-prompt.
   - `decision` defaults to `Flag rejected as noise — see rationale.`

5. On `defer`:
   - Prompt: `Rationale (required, why deferred):` — captured into `rationale`. Refuse an empty rationale.
   - Prompt: `Owner (default: $USER):` — captured for the carry-forward row.
   - The skill stages a `pending_carry_forward[]` row for Phase 2 to write; assigns a new `item_id` (e.g. `AF-03-carry`) and sets `carry_forward_ref` on the flag to that id.

6. On `skip`:
   - No state change. Move to next flag.
   - At end-of-run summary, list every skipped flag with `AF-NN` and remind the human that commit-PR remains gated.

## Iteration cap

If `len(working_set) > 12`, warn the human upfront:

```
12 flags to triage. This is unusually many. Common causes:
  - One PR is doing too much — consider splitting.
  - Agent is over-flagging — review the kind distribution.
Continue triaging? [y/N]
```

Hard cap is informational, not blocking — the human can proceed. The point is to surface that 12 flags in one PR is a workflow smell.

## Output

A list of `TriageVerdict` records for Phase 2:

```jsonc
{
  "flag_id":   "AF-03",
  "verdict":   "accept | reject | defer | skip",
  "decision":  "<one-line>",
  "rationale": "<one-line; required for reject and defer>",
  "decided_by": "<email from git config>",
  "decided_at": "<iso8601>",
  "carry_forward_stage": null | { "item_id": "...", "owner": "...", "reason": "..." }
}
```

`carry_forward_stage` is populated only for `verdict: defer`. Phase 2 reads it and writes the matching `pending_carry_forward[]` row.
