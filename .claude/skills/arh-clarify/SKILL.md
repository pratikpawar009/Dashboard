---
name: arh-clarify
description: Batch a feature's mid-stream `[NEEDS CLARIFICATION]` markers into ONE PO-facing round (artefact + tracker comment), then apply answers back to the source docs on re-invocation.
argument-hint: "[story-id] [--apply]"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Grep Glob
---
# /arh-clarify — Mid-stream batched clarification

The `clarification-marker` skill handles markers at **requirement time** — they must be resolved before `/arh-research`. This skill handles the markers that surface **after** the requirement phase has closed: ambiguities the implementation-agent (or plan-implementation, or validate-feature) hits mid-task that weren't visible at intake.

**Without `/arh-clarify`:** the agent either guesses silently (bad — see clarification-marker anti-patterns) or interrupts the user N times per session for N questions (bad — workflow killer for the PO).

**With `/arh-clarify`:** the agent records markers as it works; one batched round goes to the PO; answers flow back into the source docs in a single pass.

**Input:** `$ARGUMENTS` (story id), optionally `--apply` to import PO answers from the current CLARIFY-NN.md round.

**Precondition:** Feature folder `docs/features/$ARGUMENTS/` exists with at least one `.md` artefact and at least one `[NEEDS CLARIFICATION:` marker outside the original story's `## Clarifications` section (those should have been resolved at `/arh-intake`).

## Pipeline

```
0. Context  → 1. Scan  → 2. Bundle  → 3. Tracker comment  → 4. Apply (--apply only)
```

## Phase 0 — Context

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-context.md`

Loads:
- All `.md` files under `docs/features/$ARGUMENTS/`
- `docs/features/$ARGUMENTS/QUESTIONS.md` if the implementation-agent has been queueing markers there
- Prior rounds: `clarifications[]` in `docs/features/$ARGUMENTS/state.json` plus any `CLARIFY-NN.md` artefacts already on disk
- Resolves the next round number (= prior_max + 1)

## Phase 1 — Scan

Read and follow: `${CLAUDE_SKILL_DIR}/steps/01-scan.md`

Walks every `.md` file in the feature folder. Collects every `[NEEDS CLARIFICATION: <question>]` marker that is NOT already recorded in a prior `clarifications[]` round.

For each marker captures: source doc, line number, the raw question, the surrounding sentence (for context), and a best-effort category (`scope | security | integration | ux`).

The `QUESTIONS.md` queue (when present) is the implementation-agent's session-buffer — it carries markers that may not yet have been written into PLAN.md or the source doc inline. Treat its entries identically to inline markers; absence is fine.

**Output of this phase:** an in-memory list of `Question` records.

## Phase 2 — Bundle

Read and follow: `${CLAUDE_SKILL_DIR}/steps/02-bundle.md`

Writes `docs/features/$ARGUMENTS/clarify-<round>.md` — the PO-facing artefact. Single document, grouped by category, with one section per question. Each question gets a `Q-NN` id, the marker text, source pointer (doc + line), why it's blocking (which task / which decision), and an `Answer:` slot the PO fills in.

Writes the matching `.clarifications[]` round in `docs/features/$ARGUMENTS/state.json` (P-tier; no index mirror) with `status: asked` and the per-question records.

**Cap:** ≤7 questions per round. Beyond 7, the round is `OVERSIZE — re-scope` and the command escalates: too many open questions usually means a chunk of the story should be re-cut, not deferred into a 12-question wall.

## Phase 3 — Tracker comment

Read and follow: `${CLAUDE_SKILL_DIR}/steps/03-tracker.md`

When `integrations.tracker != none`, posts a single comment on the feature's tracker story with a link to `CLARIFY-<round>.md` and an inline summary (the questions, no answers). Updates `.clarifications[<round>].tracker_comment` in `docs/features/$ARGUMENTS/state.json` with the comment id.

Skipped silently when tracker is `none`.

## Phase 4 — Apply (only with `--apply`)

Read and follow: `${CLAUDE_SKILL_DIR}/steps/04-apply.md`

Re-invoke after the PO has filled in `Answer:` fields in `CLARIFY-<round>.md`. The phase:

1. Parses each answer.
2. Walks back to each `source_doc` and replaces the inline `[NEEDS CLARIFICATION: ...]` marker with the resolved value.
3. Appends a row to the artefact's `## Decision log` (or PRD `## Resolved questions`) per the `clarification-marker` resolution rule.
4. Sets per-question `answer`, `answered_at`, `applied_at` in state.
5. When every question is applied, sets the round's `status: resolved`.

Unanswered questions stay `status: partially-answered`; re-invoke `--apply` later when more answers land.

## Final summary

```
CLARIFY ROUND <N> {asked | applied}
──────────────────────────────────────
Story:           $ARGUMENTS
CLARIFY artefact: docs/features/$ARGUMENTS/clarify-<N>.md
Questions:       <count>  ({scope=, security=, integration=, ux=})
Tracker comment: {KEY-XX} | skipped (tracker=none)
Status:          asked | partially-answered | resolved
```

## Anti-patterns

- **Drip-feeding** — invoking `/arh-clarify` per question. Defeats the entire purpose. Queue markers across a session, fire one round.
- **Stealth resolution** — editing source docs to remove markers without running `--apply`. State and source docs drift; the audit trail breaks.
- **Bypassing the cap** — splitting one logical question into two to dodge the 7-question limit. Cap exists to force re-scoping; split the story instead.
- **Mixing intake-time and impl-time clarifications** — markers in the story's `## Clarifications` section are owned by `/arh-intake` and resolved via `clarification-marker`. `/arh-clarify` only handles markers that surface **after** that section was closed.
- **Re-asking** — emitting a question this round that was already answered in a prior round. Phase 1 scan dedupes against prior `clarifications[]`; honor the dedup.
