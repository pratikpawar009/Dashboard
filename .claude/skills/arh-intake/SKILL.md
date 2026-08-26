---
name: arh-intake
description: Parse a requirement source (file / raw text / tracker / doc URL) into a decomposed set of traced, validated stories and sync to the configured trackers. Auto-configures integrations on first run.
argument-hint: "<file-path | raw-text | tracker-key | doc-url>"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Grep Task AskUserQuestion
---
# /arh-intake — Main Orchestrator

Decide once with the whole requirement in view, then author + validate every story in
parallel, then record and sync. Execute in order. Never fail the whole pipeline because one
integration is down.

**Input:** `$ARGUMENTS`

## Step 0 — Auto-configure integrations

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-auto-config.md`

**Output:** `docs/config/issue-tracking.yaml` and `docs/config/doc-tracker.yaml` populated.

## Step 0.5 — Refresh approved facts

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00b-refresh.md`

Runs before anything is parsed, and its result is frozen for the rest of this run — Step 1 fans stories out in parallel, so every sibling must read the same, already-refreshed context rather than each re-triggering its own refresh mid-flight.

**Output:** a one-time context-refresh report (stack facts + verified patterns-skill facts), no file writes.

## Step 1 — Decide (decompose → RTM)

Read and follow: `${CLAUDE_SKILL_DIR}/steps/01-decide.md`

Invoke `decomposition-agent` **once** with `$ARGUMENTS`. It writes the full RTM (stories,
dependencies, contracts) in one context. If it returns OPEN QUESTIONS and a user is
available, resolve them with `AskUserQuestion` and re-invoke so the RTM reflects the answers.

**Output:** `docs/requirements/RTM.md` — the decided plan. No story files yet.

## Step 2 — Author + validate (parallel)

Read and follow: `${CLAUDE_SKILL_DIR}/steps/02-author-validate.md`

Spawn one `story-author-agent` **per story row, in parallel** — the rows are independent and
all decisions are already in the RTM. Each writes its own story file, validates in place,
and returns a result payload. Collect all payloads.

**Output:** `docs/stories/<ID>.md` per story; a payload per story.

## Step 3 — Record state + RTM status

Read and follow: `${CLAUDE_SKILL_DIR}/steps/03-record.md`

In one serial pass (never in parallel — these are shared files), write each story's entry to
`docs/state/features.json` and set each RTM row's `Status` from the collected payloads.

## Step 4 — Doc tracker sync

Read and follow: `${CLAUDE_SKILL_DIR}/steps/04-doc-tracker-sync.md`

Sync RTM and validated stories to the configured doc tracker. Skipped if `doc_tracker = local`.

## Step 5 — Issue tracker sync

Read and follow: `${CLAUDE_SKILL_DIR}/steps/05-issue-tracker-sync.md`

Create Epics + Stories in the configured tracker for validated stories. Skipped if
`issue_tracker = none`.

## Final summary

Print this block exactly:

```
INTAKE COMPLETE
──────────────────────────────────────
Source:       {document name or "raw text"}
RTM:          docs/requirements/RTM.md ({N} stories, {E} epics)
Doc tracker:  {page URL}  |  Skipped (local mode)

Stories:
  {EPIC}-{SEQ}: {Name}   {P1|P2|P3}  →  validated  →  {KEY-XX} {URL}
  {EPIC}-{SEQ}: {Name}   {P1|P2|P3}  →  validated  →  {KEY-XX} {URL}

Escalated:
  {EPIC}-{SEQ}: {Name}   →  {reason}

Open questions (from decomposition, confirm/correct):
  - {question} → assumed {value}

Assumptions to confirm (author choices the source did not give — from story Decision logs):
  {EPIC}-{SEQ}: {topic} = {value} ({reason})

Next: /arh-research <STORY-ID>
```

Aggregate the `assumptions_list` from every Step 2 author payload into the "Assumptions to
confirm" block, so no invented specific (NFR budgets, WCAG levels, enums) stays invisible.

## Error handling

| Failure point | Behaviour |
|---|---|
| Step 0 detects no MCP | Proceed in local mode; Steps 4–5 skip gracefully. |
| Step 1 produces zero stories | Stop with: `No requirements could be parsed from $ARGUMENTS`. |
| A story escalates (decomposition defect) | Record it; collect all escalations and re-run Step 1 once with the reasons, or surface them. Do not loop an author. |
| Step 2 one author fails | Continue with siblings; record the failure; report at end. |
| Step 4 or Step 5 MCP unavailable | Log the failure, continue, surface in final summary. |
