---
name: phase-preconditions
description: Precondition matrix for requirement-phase commands. Loaded by every workflow command's Step 0 to abort early if prior phase incomplete.
when_to_use: Step 0 of /arh-research, /arh-plan-requirements, /arh-plan-implementation. Loaded by /arh-sync to verify configs exist.
user-invocable: false
allowed-tools: Read
---
# Phase Preconditions

Single source of truth for which command requires which prior state. Every requirement-phase command MUST consult this matrix before running its body. Aborts early with a helpful next-step message instead of failing mid-run.

## State location

Project state splits by phase:

- **Pre-plan phases** (intake, validate-story, research): `docs/state/features.json[<id>]` — entry per feature.
- **Post-plan phases** (plan-requirements onward): `docs/features/<id>/state.json` — per-feature file. Created at `/arh-plan-requirements` (the migration point).

Each phase reads from the path appropriate for its phase. No runtime fallback — readers hardcode the path.

## Matrix

| Command | Reads from | Required state | Failure message |
|---|---|---|---|
| `/arh-research <id>` | `docs/state/features.json[<id>]` | `story == "validated"` | `Run /arh-validate-story <id> first.` |
| `/arh-plan-requirements <id>` | `docs/state/features.json[<id>]` | `research == "complete"` AND `research_verdict in {GO, GO-WITH-CONDITIONS}` | `Run /arh-research <id> first.` OR `Research verdict is <X>; address blockers before /arh-plan-requirements.` |
| `/arh-plan-implementation <id>` | `docs/features/<id>/state.json` | `gate == "APPROVE"` AND `docs/adr/0001-tech-stack.md` exists with at least one entry in § Decision Frameworks list | `Product Gate is <X>; pass it via /arh-plan-requirements <id>.` OR `No tech stack declared. Run `/arh-init` to write ADR-0001.` |
| `/arh-implement <id>` | `docs/features/<id>/state.json` | `gate == "APPROVE"` AND `plan == "complete"` | `Run /arh-plan-implementation <id> first.` |
| `/arh-validate-feature <id>` | `docs/features/<id>/state.json` | `impl == "branch:<name>"` | `Run /arh-implement <id> first.` |
| `/arh-review <id>` | `docs/features/<id>/state.json` | `validation == "<DATE> P=<P>/<TOTAL>"` (any P) | `Run /arh-validate-feature <id> first.` |
| `/arh-security-review <id>` | `docs/features/<id>/state.json` | `review == "<verdict>"` | `Run /arh-review <id> first.` |
| `/arh-iterate-design <id>` | `docs/features/<id>/state.json` | `prd == "complete"` AND `design != "n/a"` AND `integrations.design != "none"` | `Run /arh-plan-requirements <id> first; no PRD to iterate from.` OR `Feature <id> has design = n/a (backend-only).` OR `integrations.design == none. Run `harness add integration design <provider>` first.` |
| `/arh-sync` | (both files iterated) | `docs/config/issue-tracking.yaml` exists OR `docs/config/doc-tracker.yaml` exists | `Run /arh-init first to populate tracker configs.` |
| `/arh-fix` | (none — bypass lane) | NONE — `/arh-fix` is the hotfix lane and carries no phase precondition. Its own Step 1 architectural-bounce guard routes non-hotfix defects to `/arh-intake`. | (n/a) |

## Clarification gate (open-questions hard gate)

No phase may start while its input artifact still carries unanswered questions. Before applying the matrix, scan the prior-phase artifact:

| Command | Scan this artifact |
|---|---|
| `/arh-research <id>` | `docs/stories/<id>.md` |
| `/arh-plan-requirements <id>` | `docs/research/<id>.md` |
| `/arh-plan-implementation <id>` | `docs/features/<id>/REQUIREMENTS.md` |
| `/arh-implement <id>` | `docs/features/<id>/PLAN.md` |

An artifact has an **unresolved clarification** when it contains EITHER:

- one or more `[NEEDS CLARIFICATION: ...]` markers, OR
- a non-empty `## Open questions` / `## Clarifications` section — any content line that is not blank, not an HTML comment, and not a scaffold placeholder comment.

On a hit, abort:

`Unresolved clarifications in <artifact>: <n> open item(s). Answer them (delete the marker / clear the section) or record an explicit skip in the artifact before /<command>. Open questions cannot cross a phase boundary.`

Non-negotiable, same as the matrix preconditions — `--skip-preconditions` does not bypass it. The only legitimate exit is to resolve the question or escalate it to the user.

## Procedure (every command's Step 0 follows this)

1. Read the state file declared in the matrix's "Reads from" column for the command being gated. If missing or malformed, abort:
  - For pre-plan commands: `State file missing; run /arh-init first.` (when `docs/state/features.json` absent) OR `Feature <id> not in state; run /arh-intake or /arh-import first.` (when id missing)
   - For post-plan commands: `Per-feature state missing; run /arh-plan-requirements <id> first.` (when `docs/features/<id>/state.json` absent)
2. Apply the matching matrix row above. If the precondition holds, continue. If not, abort the command with the matrix's failure message, **then offer recovery per § Recovery options below** — never leave the user at a dead end.
3. **Clarification gate** (every gated command): run the "## Clarification gate" scan above against the prior-phase artifact. If any unresolved item is found, abort with its message, then offer recovery per § Recovery options. This blocks a phase from starting on top of unanswered open questions.
4. **Stack check** (for `/arh-plan-implementation` only): read `docs/adr/0001-tech-stack.md` § Decision (Frameworks list). If the ADR is missing or the Frameworks list is empty, abort with the second failure message above, then offer recovery per § Recovery options. The file plan, ADRs, and task table all need at least one framework declared to anchor implementation choices.
5. Never proceed to Step 1 of the command unless this skill returns `OK` from steps 2, 3, and (where applicable) 4.

## Recovery options (a failed gate is not a dead end)

Gates run in the **main session**, so after printing the failure message, ASK the user how to proceed — recommendation first, 2–3 concrete options, never a bypass. The blocked command stays aborted; the chosen option is the recovery path toward re-running it.

| Failure class | Recommended option (offer first) | Other options |
|---|---|---|
| `story == "draft"` | Run `/arh-validate-story <id>` now | Show the story for review first; stop here |
| `story == "escalated"` and/or open clarifications > 0 | **Walk through each open clarification now, one at a time** — record the user's answer in the story (delete the marker / fill the section), then run `/arh-validate-story <id>` | List the open questions and stop (user resolves offline); stop here |
| `research != "complete"` | Run `/arh-research <id>` now | Stop here |
| `research_verdict ∈ {SPIKE, BLOCK}` | Show the blockers from `docs/research/<id>.md`, resolve with the user, then re-run `/arh-research <id>` | Stop here |
| `gate != "APPROVE"` | Re-run `/arh-plan-requirements <id>` to pass the Product Gate | Show the gate verdict + what failed; stop here |
| `plan != "complete"` | Run `/arh-plan-implementation <id>` now | Stop here |
| `review` not set (`/arh-security-review`) | Run `/arh-review <id>` now | Stop here |
| State file / feature id missing | Run `/arh-init` (no state at all) or `/arh-intake` / `/arh-import` (feature unknown) | Stop here |
| ADR-0001 missing / empty Frameworks | Run `/arh-init` to record the tech stack | Stop here |

Rules:

- Present the options explicitly (numbered or via the question UI) with the recommended one first and a one-line reason. Wait for the user's pick — do NOT auto-run the recovery command.
- After the recovery action completes successfully, offer to re-run the originally blocked command.
- Never offer "proceed anyway" — that is the forbidden bypass (§ Override).

Stack is irrelevant until `/arh-plan-implementation` § 2 (File and Module Plan) — story / validation / research / PRD describe *what* and *why*, not *how*. The `/arh-plan-implementation` matrix row encodes the ADR-0001 stack requirement; upstream commands carry no stack precondition.

## Override

`--skip-preconditions` is forbidden. Preconditions are not negotiable. The right action when blocked is to fix the prior phase, not bypass the check. If a feature legitimately needs to skip a phase (e.g. trivial bug fix that needs no research), record the skip explicitly in the appropriate state file for that phase (pre-plan: `docs/state/features.json[<id>]`; post-plan: `docs/features/<id>/state.json`) — for example `research: "skipped:trivial"` — and document the reason in the story file's "Phase skips" section.

## Patterns-skill freshness check (G15)

Canonical procedure — gate steps reference this section; do not re-paste it.

For every `<framework>-patterns` (or `<runner>-patterns`) skill bound to the command's agent (via composer-wired `stacks_patterns_skills`), check whether the body still contains scaffold-only `TODO` placeholder markers (HTML-comment form per F-013).

If any body is unfilled, print **one warning per skill** before proceeding (do NOT abort):

```
⚠ <framework>-patterns body is unfilled; <command-specific consequence>.
  Fill .claude/skills/<framework>-patterns/SKILL.md to apply org conventions.
```

The `<command-specific consequence>` is supplied by the calling gate step (e.g. "research pattern-map will be generic", "security review may miss stack-specific idioms"). The command proceeds with the framework's canonical/general knowledge when bodies are unfilled — common on first run, before the team fills them. The warning surfaces the gap to the user every run.
