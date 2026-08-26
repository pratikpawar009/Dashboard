---
name: arh-init
description: Populate harness state — gather context, tracker configs, then delegate commands + memory file + architecture ADRs to bootstrap-agent. Detects brownfield.
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Grep Glob
---
# /arh-init — Main Orchestrator

Initialise harness state from project signals plus user input. Idempotent — safe to re-run when stack, domain, personas, or integrations evolve.

Hybrid flow: the interactive + MCP phases (0–3, 5) run inline here in the main session because they need live user dialogue; the analysis + write phase (4) is delegated to the `bootstrap-agent` subagent.

**Input:** `$ARGUMENTS` (optional one-line project description).

## Pipeline

```
0. Detect signals          (main, read-only)
1. Gather info             (main, interactive: 9 Qs + conventions + overwrite pre-approval)
2. Tracker/design config   (main, MCP discovery + picks)
3. Folders + RTM + ADR-0001(main, write)
4. Architecture decisions  (main, interactive: ask gaps w/ recommendations)
   → INVOKE bootstrap-agent (subagent loads skills: project-commands → project-memory → architecture-decision)
5. Brownfield branch       (main, interactive: suggest /arh-import)
6. Deep scan               (main, brownfield-only, mandatory — scan/approve/write)
```

## Phase 0 — Detect signals

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-detect.md`

Carry the greenfield/brownfield verdict forward — you hand it to `bootstrap-agent` in Phase 4 and gate Phase 5 on it.

## Phase 1 — Gather info

Read and follow: `${CLAUDE_SKILL_DIR}/steps/01-gather.md`

This phase also collects the Conventions answer and runs any project-memory-file overwrite pre-approval here, in the main session.

## Phase 2 — Tracker/design config

Read and follow: `${CLAUDE_SKILL_DIR}/steps/02-tracker.md`

## Phase 3 — Folders + RTM stub + ADR-0001

Read and follow: `${CLAUDE_SKILL_DIR}/steps/03-folders.md`

When `harness.yaml` declared no stack, this phase settles it via the stack guard (skill `stack-selection`) before writing ADR-0001 — detect for brownfield, recommend for greenfield — and records it by editing `harness.yaml stacks[]` directly (the source of truth). ADR-0001 § Decision is then sourced from `harness.yaml`, so config and ADR agree. Wiring the `<framework>-patterns` playbooks: for brownfield, this phase runs `harness generate` itself right after the stack is recorded, so every patterns skill exists before Phase 4 and Phase 6 need it; for greenfield it stays deferred to a user-run `harness generate` (surfaced in the Final summary; safe to re-run — filled patterns skills are preserved).

## Phase 4 — Architecture decisions + delegate

### Step 4.0 — Architecture decisions (main session, interactive)

Read and follow: `${CLAUDE_SKILL_DIR}/steps/04-architecture-decisions.md`

Settle the high-level architecture decisions WITH the user here. The step frames them as six role-agnostic dimensions (runtime, state, interfaces, execution, trust, operability), instantiated from the declared stacks/roles — ask only the live, unsettled ones, with a recommendation each; skip anything already answered by the declared stacks / `docs/prd/*` / `docs/config/domains.json`. Record them to the answer log. The subagent cannot ask, so this must happen before the invoke.

### Step 4.1 — Invoke `bootstrap-agent`

**Patterns-skill freshness check (G15).** The agent consults the `<framework>-patterns` skills for stack-specific commands (skill `project-commands`) and architecture topology (skill `architecture-decision`). For brownfield, Phase 3 already ran `harness generate`, so every declared stack's patterns file exists on disk by this point — G15 only ever warns about a body still carrying scaffold-TODO content, never a missing file. Before invoking, run the patterns-freshness check per skill `phase-preconditions` § G15 — warn per unfilled skill (do NOT abort), consequence: "commands + architecture inference will be generic".

Invoke the `bootstrap-agent` subagent. Pass it: (1) the greenfield/brownfield verdict from Phase 0, (2) the Phase-1 answer log (Conventions, Personas, Domain, Target platforms, overwrite approvals) **plus the Step-4.0 `architecture:` block**. The agent already carries a `<framework>-patterns` skill per stack and reads `docs/adr/0001-tech-stack.md` for the recorded stack. All interactive decisions were resolved in Phases 1–2 and 4.0.

The agent works through three knowledge skills it loads, in this order:

1. Skill **`project-commands`** — writes `docs/config/project-commands.yaml` + `docs/config/stack-smoke.md`.
2. Skill **`project-memory`** — verifies the project memory file against its canonical sections: fills TODO slots from the Phase-1 answers and adds any absent sections (incl. the `@imports` + Where-to-look wiring) without clobbering. (Commands first so the `@import docs/config/project-commands.yaml` check resolves within the run.)
3. Skill **`architecture-decision`** — **records the Step-4.0 architecture decisions** + stack topology as ADR(s) (next free id from `0002`) — prefer ONE consolidated ADR. Brownfield reverse-engineers the existing architecture and flags gaps. It does not invent decisions the user did not make.

Consume the agent's hand-off report: surface the memory-file overwrites it performed, the ADR ids it wrote, and any flagged missing pieces (brownfield) in the Final summary.

## Phase 5 — Brownfield branch (suggest /arh-import)

Read and follow: `${CLAUDE_SKILL_DIR}/steps/05-brownfield.md`

Only when Phase 0 reported `Mode: brownfield`.

## Phase 6 — Deep scan (brownfield, mandatory)

Read and follow: `${CLAUDE_SKILL_DIR}/steps/06-deep-scan.md`

Only when Phase 0 reported `Mode: brownfield` — and when it did, this phase always runs, over the whole repo, no skip and no budget cap. There is nothing to ask the user here; the harness needs real, cited knowledge of the existing codebase before any implementation work starts. Delegates the actual scanning to `bootstrap-agent` (skill `deep-scan-verification`) so scan detail never enters this session's context — only counts and grouped facts come back for approval here.

## Final summary

```
BOOTSTRAP COMPLETE
──────────────────────────────────────
Signals detected:    <list>
Mode:                greenfield | brownfield
Configs:             docs/config/issue-tracking.yaml, docs/config/doc-tracker.yaml, docs/config/project-commands.yaml
Folders:             docs/{stories,research,features,requirements,adr,sessions}/ created
RTM stub:            docs/requirements/RTM.md
ADR-0001:            docs/adr/0001-tech-stack.md
Memory file:         populated  (personas: <N>, domain entries: <M>)
Memory overwrites:   <list reported by agent | none>
Architecture ADRs:   <ids + titles from agent report, e.g. ADR-0002 system architecture>
Flagged (brownfield):<undocumented layers / missing configs | none>
Deep scan:           <not offered (greenfield) | N facts approved, M deferred>
Patterns:            <W> unfilled <framework>-patterns warnings
TODOs remaining:     <count>

Next:
  Greenfield → run `harness generate` first to wire the <framework>-patterns playbooks into
              agents (safe to re-run; filled skills preserved), then /arh-scaffold (if stack
              provides one) then /arh-intake
  Brownfield → <framework>-patterns already wired by this run → /arh-import --jira-jql /
              --confluence-space / --from-files
```
