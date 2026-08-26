---
name: project-commands
description: Write a project's command + smoke config — project-commands.yaml (typecheck/test/lint/build/preflight/design_check) and stack-smoke.md per stack. Used by bootstrap-agent.
user-invocable: false
---
# Project commands + stack smoke

Write two config files. Consult the `<framework>-patterns` skill body for stack-specific commands; fall back to the framework's canonical dev/test invocation when the patterns body is still scaffold-TODO. Prefer existing wrappers (`make test`, `pnpm typecheck`) over raw commands.

## `docs/config/project-commands.yaml`

```yaml
typecheck:           <command>
test:                <command>
test_unit:           <command>
test_integration:    <command>
test_e2e:            <command>
lint:                <command>
format:              <command>
build:               <command>

# Optional — set ONLY when a frontend stack is recorded in ADR-0001. Run by
# /arh-implement Step 1b as the "design check" evidence dimension. Examples:
#   axe tests/a11y                           # accessibility
#   playwright test tests/smoke/console.spec.ts   # console-error scan
#   pa11y-ci --sitemap http://localhost:3000/sitemap.xml
#   lighthouse-ci autorun --collect.staticDistDir=./dist
# Absent or empty → /arh-implement raises an AF-NN with kind: evidence-na,
# source: design_check, which the engineer triages at /arh-human-review.
design_check:        <command>

# Per-extension overrides (post-edit hooks use these)
typecheck_for_ts:    <command>
typecheck_for_py:    <command>
format_for_ts:       <command $FILE>
format_for_py:       <command $FILE>

# Preflight: dep-install + smoke-import commands. validate-feature Phase 1
# runs these. Non-zero exit fails Phase 1. Add entries whenever a validation
# round surfaces a missing dep — every missed-dep error signals a preflight gap.
preflight:
  - <command>
```

## `docs/config/stack-smoke.md`

One `# <stack-id>` section per stack id recorded in `docs/adr/0001-tech-stack.md` § Decision. Validate-feature Phase 2b walks each section (prefers `Docker:`, falls back to `Run:`).

```markdown
# <stack-id>

- Deps: <service-start command>               # optional list; backing services started BEFORE Migrate/Run/Docker (see below)
- Migrate: <command>                          # optional, runs before Run/Docker
- Run: <direct dev command, with --port N>
- Docker: <containerized equivalent>          # or `(n/a — <reason>)` to skip
- Check: <healthcheck URL>                    # optional override; defaults to http://127.0.0.1:<N>/health derived from --port flag
```

`(n/a — ...)` on both `Run:` and `Docker:` → stack skipped (mobile/desktop without serve-on-port, pure libraries).

### Service dependencies (`Deps:`)

OPTIONAL. Set it only when a stack needs a backing service to boot or serve — a
database, cache, queue, or search engine. Detect the need from existing signals,
never invent one: a service driver in the lockfile (`pg`, `redis`, `kafkajs`,
`psycopg`, …), a `migrations/` directory, or a connection env var
(`DATABASE_URL`, `REDIS_URL`, …). No such signal → omit `Deps:` entirely (most
pure-compute or static stacks have none).

`Deps:` is a **list** — one entry per service — so a stack that needs several
(Postgres + Redis) is covered, and each entry gets its own start + verdict:

```markdown
# orders-api
- Deps:
    - docker compose up -d postgres
    - docker compose up -d redis
- Run: pnpm dev --port 3000
```

When a single command starts everything, one inline entry is enough
(`- Deps: docker compose up -d`). For a service something else runs, record it
honestly so the runner skips it: `- Deps: (external — uses ${DATABASE_URL})`.

Two rules keep this safe:

- **No double-start.** List only services the `Run:`/`Docker:` command does
  **not** already bring up. If `Docker:` is a full `docker compose up` that
  already includes the database, leave that service out of `Deps:` — otherwise
  the second start collides on the port.
- **Honest gap, never a silent skip.** A service signal exists but you have no
  start command (team never said how to run the DB) → write
  `- Deps: [NEEDS CLARIFICATION — no start command for <service>]`. This surfaces
  at validate-feature / evidence-pass as a FAIL the human must answer, never as a
  passing check against an absent dependency.

## Required artefacts

`typecheck`, `test`, `lint`, `format` in `project-commands.yaml`: MANDATORY for hooks. `preflight:` + `stack-smoke.md`: MANDATORY when any stack recorded in ADR-0001 declares a runnable framework. Missing → validate-feature Phase 2b emits `stack-smoke-not-configured` and downgrades verdict to PARTIAL.

`design_check:` is OPTIONAL. Set it when a frontend stack is declared (`react`, `vue`, `svelte`, `angular`, `next`, `remix`, `sveltekit`, `nuxt`, `astro`, `solidstart`, `qwik`). Absent or empty → `/arh-implement` Step 1b raises an `evidence-na` agent flag rather than failing; the engineer accepts or rejects the N/A at `/arh-human-review`. Backend-only projects leave it blank.

The keys `typecheck`, `test_unit` (fallback `test`), `lint`, `build`, `design_check`, plus `stack-smoke.md` Run:/Docker: lines, are the canonical sources `/arh-implement` Step 1b reads to assemble the six-dimension evidence packet. Keeping them filled in (or honestly blank) is what makes the hand-off receipt trustworthy.
