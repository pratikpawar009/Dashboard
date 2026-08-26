# Step 3 — Record state + RTM status

Goal: persist the results from Step 2 to the two shared files. Because these are shared, the
orchestrator does this itself in **one serial pass** — never in parallel with, or inside, the
author agents (that is how write races happen).

## State write (mandatory, unconditional)

For each **Story-row** payload collected in Step 2, write its entry to
`docs/state/features.json` (the pre-plan index). Create the file with `{}` first if it does
not exist. Epic rows are not features — they get no state entry.

```json
{
  "<EPIC>-<SEQ>": {
    "story": "validated",
    "story_priority": "<P1|P2|P3>",
    "story_independent_test": <bool>,
    "needs_clarification_count": <int>,
    "rtm_source_sha": "<Source hash copied from the RTM file header>",
    "phase": "story-validated",
    "last_updated": "<iso8601>"
  }
}
```

- `story` is a STATUS literal — `validated`, `escalated`, `draft`, or `imported:<source>` —
  never a tracker key. Tracker keys are written by Step 5 into `tracker_story`.
- `rtm_source_sha` is **copied from the RTM header line `Source hash`** — a content hash of
  the intake input, not a git SHA. Do not run `git rev-parse` here (wrong in no-VCS or
  nested-repo projects).
- `story_independent_test` comes from the author payload, derived by rule (see
  `story-author-agent`): `true` when the story has no upstream dependency or depends only via
  a listed Contract; a non-contract code dependency is a decomposition failure and escalates.
- On **escalated**: `"story": "escalated"`, `"phase": "story"`.
- On import (`/arh-import` rows): `"story": "imported:<source>"`, and the row was not
  re-authored.

The `story` literal drives `phase-preconditions` — `/arh-research <id>` requires
`state[id].story == "validated"`. Skipping this write blocks research after a clean pass.

## RTM status

Set each RTM row's `Status` column to match (`validated` / `escalated`). Do not touch any
other column. Preserve manually-edited rows.

## Verify

Reconcile against the RTM, not just the payloads collected in Step 2 — a parallel author that
crashed or timed out returns no payload at all, so a check keyed on collected payloads would never
notice the gap.

1. Build the expected set from every Story-row in `docs/requirements/RTM.md` (epics excluded).
2. Every expected story must have both a `features.json` entry and an RTM `Status`. Any that has a
   payload but is missing a write → re-record it before the final summary.
3. Any expected story with **no payload** (author never returned) → record
   `"story": "escalated"`, `"phase": "story"` with reason `author-no-result`, set its RTM `Status`
   to `escalated`, and surface it in the summary. Do not silently drop it — a missing state entry
   blocks `/arh-research <id>` downstream with no explanation.
