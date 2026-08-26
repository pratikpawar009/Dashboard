---
name: arh-explain
description: Show full lineage for a feature — story, research, PRD, plan, impl branch, validation results, review status. Pulls from per-feature state.json (post-plan) or features.json index (pre-plan).
argument-hint: "[feature-id]"
disable-model-invocation: true
allowed-tools: Read Grep
---
# /arh-explain

Print the lifecycle lineage of `$ARGUMENTS`.

Steps (perform inline; this is a thin formatter):

1. Determine phase from `docs/state/features.json[$ARGUMENTS]`. If the index entry's `phase` field is `imported | story | story-validated | research`, read the record from the index. Otherwise read `docs/features/$ARGUMENTS/state.json` (post-plan).
2. If neither file has the record, print a helpful error suggesting `/arh-import` or `/arh-intake`.
3. Print a table:
   ```
   Story:      docs/stories/$ARGUMENTS.md  (imported:jira / authored)
   Research:   docs/research/$ARGUMENTS.md or null
   PRD:        docs/features/$ARGUMENTS/REQUIREMENTS.md or null
   Plan:       docs/features/$ARGUMENTS/PLAN.md or null
   Impl:       branch:feature/$ARGUMENTS or null
   Validation: <status>
   Review:     <status>
   Phase:      <current>
   Updated:    <iso8601>
   ```
