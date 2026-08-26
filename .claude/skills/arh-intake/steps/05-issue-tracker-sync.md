# Step 5 — Issue tracker sync

Goal: create issues in the configured issue tracker for every Validated story. Escalated stories do not sync. Skipped entirely when `provider: none`.

## Procedure

Read `docs/config/issue-tracking.yaml`.

**Sanity check before delegating (mandatory).** If `provider != none` but ANY required field is missing or holds a placeholder value (`TODO`, `FILL`, empty string, `null`, `<…>`), DO NOT silently skip. This means Step 0 was bypassed or the file was hand-edited mid-run.

Action when this happens:

1. Print loudly:
   ```
   Issue tracker: CANNOT SYNC — docs/config/issue-tracking.yaml has placeholder values for: <list of fields>.
   Re-run /arh-intake to trigger discovery, OR edit the file manually and re-run.
   ```
2. Update `docs/state/features.json` for each newly-validated story:
   `tracker_story: "pending:<reason>"` (e.g. `pending:config-incomplete`) — distinct from the success literal so `/arh-explain` and `/arh-trace` surface it.
3. Exit Step 5 with a non-zero summary; downstream phases still run, but stories carry the `pending:` literal until the operator fixes the config.

Only when the config is complete do you delegate to `issue-tracking-agent` with the list of Validated stories and the config.

The agent:

1. For each Epic-id in the RTM with at least one Validated story, ensure an Epic exists in the tracker (create or reuse by label).
2. For each Validated story, create the corresponding tracker issue:
   - Type: `story` (or `task` if `story` is unavailable for the project).
   - Parent / Epic link via `epic_story_link_field`.
   - Priority: from the story's `Priority` (`P1`/`P2`/`P3`), mapped via `priorities` in config.
     If the mapping is `null` (project has no priority field), apply `P1`/`P2`/`P3` as a label instead.
   - Labels: from `labels` config plus story-specific tags.
   - Body: link back to the story file path AND the doc tracker page URL when available.
3. Patch the story file's traceability header with the resulting tracker key + URL.
4. Write the key into the RTM `Tracker` column for that row (and the Epic row's `Tracker` for
   the created Epic), and record it in `docs/state/features.json` under `tracker_story`. The
   RTM `Tracker` column is the human-facing traceability view; `tracker_story` is the
   machine-read source.
5. Ensure each created story issue sits at the `validated` stage. Creation normally lands the
   issue in the tracker's initial status, which the provider status map points `validated` at
   — so no transition is usually needed. Only when the tracker creates issues in a different
   state, issue a best-effort `transition` (agnostic target stage `validated`; the provider
   skill maps it). This is non-blocking: the created key is already recorded, so on failure
   log and continue — never roll back the created issue.

## Linear / GitHub Issues / GitLab / Azure DevOps

Each provider has the same shape; the agent calls the matching tools — `mcp__linear__createIssue`,
`mcp__github__createIssue`, `mcp__ado__createWorkItem`, `mcp__gitlab__create_issue`.

**GitLab creates no Epic.** Skip step 1 above and go straight to the story issues. Tag each story
with its Epic-id as the label `epic::<EPIC-ID>` instead.

Leave the RTM's Epic rows with an empty `Tracker` column. Do **not** write `pending:` against them
— that literal means "not yet", and an empty Epic row here is permanent by design. Do not create
a placeholder issue to fill the column: a stand-in is indistinguishable downstream from a real
epic, so `/arh-trace` would report Epic-level traceability that does not exist.

## Output

```
Issue tracker:
  Epics:    <count>   ({KEY-XX} ...)
  Stories:  <count>   ({KEY-XX} ...)
```

## Edge cases

- A story already references an existing key in its header → idempotent: update body, do not create a duplicate.
- Project lacks Subtask issue type → log: phase subtasks created by `/arh-research`, `/arh-plan-requirements`, `/arh-plan-implementation` will be skipped.
- Rate limit hit → backoff with jitter, resume after the budget refreshes; never silently drop a story.
