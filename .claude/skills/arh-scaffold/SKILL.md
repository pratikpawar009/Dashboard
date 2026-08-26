---
name: arh-scaffold
description: Greenfield code skeleton — invokes scaffold-agent which loads <framework>-patterns skills per declared stack. Skip on brownfield.
argument-hint: "[--force] [--skip-install] [--skip-run-smoke] [--lint-strict]"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Grep Glob
---
# /arh-scaffold — Main Orchestrator

Create source-tree skeleton for declared stacks. **Greenfield only.** Refuses to overwrite existing manifests without `--force`.

## Pipeline

```
0. Brownfield gate            (main, read-only)
   → INVOKE scaffold-agent     (init → glue → 5-gate verify)
2. Summary                    (main: consume the agent's gate report)
```

## Phase 0 — Brownfield check

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-brownfield-check.md`

## Phase 1 — Delegate to scaffold-agent

**Patterns-skill freshness check (G15).** Before delegating, run the patterns-freshness check per skill `phase-preconditions` § G15 — warn per unfilled skill (do NOT abort), consequence: "the scaffold will fall back to package-manager-native init".

Invoke `scaffold-agent` with `$ARGUMENTS`. The agent loads every `<framework>-patterns` skill listed in its frontmatter (one per declared stack — composer auto-wires them). Each `<framework>-patterns` skill body is the team's stack scaffold playbook (init command, file layout, lint/format/test wiring).

The agent does NOT invent stack idioms — it follows whatever the team filled into the `<framework>-patterns` skill bodies. Empty body → falls back to package-manager-native init (`pnpm init`, `uv init`, `cargo init`, `go mod init`).

The agent owns the whole worker pass, in order: **create** the skeleton → **glue** it to the harness configs (`docs/config/project-commands.yaml`, `tsconfig.json` paths ↔ rule globs, `.github/workflows/ci.yml` stub, `.editorconfig` / `.gitignore` / `README.md` stubs) → **verify** via skill `scaffold-verification` (install → typecheck → lint → test smoke → run smoke, stop on the first failed gate). Verify runs last so it sees the glued configs. Consume the agent's per-gate report for the summary.

## Phase 2 — Final summary

Per-stack, per-gate, per-entrypoint table. Quote the actual command run and outcome on every line. No bare PASS / SKIP — show evidence.

```
SCAFFOLD COMPLETE
──────────────────────────────────────
Stacks initialised: <list of frameworks>
Files created:      <count>
Files NOT touched:  <count>  (existing; force-able with --force)
CI workflow:        .github/workflows/ci.yml      (when integrations.ci=github-actions)

Verification:
  ✓ [web] install   PASS  `pnpm install`              (412 packages, 38.2s)
  ✓ [web] typecheck PASS  `pnpm tsc --noEmit`         (0 errors)
  ✓ [web] lint      PASS  `pnpm eslint .`             (3 warnings)
  ✓ [web] test      PASS  `pnpm vitest run`           (1/1, 0.9s)
  ✓ [web] run:dev   PASS  `pnpm next dev -p 3001`     (Ready in 1.4s, GET / 200)
  ✓ [web] run:web   PASS  `pnpm web`                  (Ready in 1.7s, GET / 200)

Next: /arh-init (if not run yet) → /arh-intake <first-requirement>
```

If any gate or entrypoint failed, the matching line shows `FAIL`, the failing
command, the exit code, and the last 5 lines of stderr. The summary is FAIL
overall — do not declare COMPLETE while any line is FAIL.
