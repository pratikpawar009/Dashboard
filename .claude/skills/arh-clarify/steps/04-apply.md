# Phase 4 — Apply (only when invoked with `--apply`)

Goal: import the PO's answers from `CLARIFY-<round>.md` back into the source docs and state.

## Precondition

`/arh-clarify $ARGUMENTS --apply` is only valid when at least one round in `docs/features/$ARGUMENTS/state.json` at `.clarifications[]` has `status: asked | partially-answered`. If every round is `resolved`, emit `nothing to apply — all rounds resolved` and exit zero.

## Procedure

Find the most recent non-resolved round. Read its artefact: `docs/features/$ARGUMENTS/clarify-<round>.md`.

For each `Q-NN` block in the artefact:

1. Parse the `Answer:` body. Strip surrounding whitespace and HTML comments (`<!-- ... -->`).
2. If empty, leave this question untouched — it'll stay unanswered for the next `--apply` pass.
3. If non-empty, apply the answer:
   - Resolve the marker in `source_doc`. Open the file, find the line matching `source_line` (re-check the marker text — if the file has been re-written and the line moved, grep for the marker text instead and fail with `marker drift detected at <doc>: marker no longer at recorded line <N>` rather than blindly editing a different line).
   - Replace the inline `[NEEDS CLARIFICATION: <text>]` with the resolved value. The PO's `Answer:` body provides the substitute. When the substitute is a short value (≤80 chars), inline it directly. When longer, replace the marker with a short summary and append the full answer to `## Decision log` (or PRD `## Resolved questions`).
   - Append a `## Decision log` row per `clarification-marker` resolution rule:
     ```
     - <YYYY-MM-DD> <Q-NN>: <one-line summary of the answer> (per PO via /arh-clarify round <N>)
     ```
4. Update the state record at `docs/features/$ARGUMENTS/state.json`:
   - `.clarifications[<round>].questions[<i>].answer` = the answer body
   - `.answered_at` = iso8601 now
   - `.applied_at` = iso8601 now
5. If `source_doc == QUESTIONS.md`, no inline marker to replace — the queue line was already truncated in Phase 2. Just record the answer in state and the Decision log of the doc the question was blocking (look up `blocking` task → owning section in PLAN.md).

## Round status update

After processing every `Q-NN`:

- All questions now have `answer != null` → set `.clarifications[<round>].status = resolved` in `docs/features/$ARGUMENTS/state.json`.
- Some still `null` → set `status = partially-answered`. Emit a list of unanswered qids in the summary so the user knows what's still open.

## Count update

Update `.needs_clarification_count` in `docs/features/$ARGUMENTS/state.json` to the new total unanswered count across all rounds (sum of questions where `answer == null`).

## Tracker reply (optional)

When `integrations.tracker != none` AND the round just transitioned to `resolved`, post a single follow-up comment on the original `tracker_story`:

```
**Clarifications round <N> — resolved.** All <count> questions answered. Source docs updated. Engineer continuing on $ARGUMENTS.
```

Skip for `partially-answered` — wait until full resolution before the closing comment.

## Failure modes

- **Marker drift** — source doc has been re-edited and the marker is no longer at the recorded line. Phase fails fast (see step 1 above). User fixes manually, then re-runs `--apply`.
- **Multiple markers with same text** — when one source doc has duplicate marker strings, prefer the one at `source_line`. If `source_line` no longer has a marker, fail with drift.
- **Answer ambiguous** — PO's answer doesn't unambiguously resolve a binary marker. Don't guess; emit `Q-NN: ambiguous answer — re-asking next round` and leave the marker in place. The next bare `/arh-clarify` re-bundles it.
