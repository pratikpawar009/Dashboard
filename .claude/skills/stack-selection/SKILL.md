---
name: stack-selection
description: Settle the tech stack when none is declared — a pinned manifest→stack detect table for brownfield autofill, and a recommendation rubric for greenfield. Feeds ADR-0001.
when_to_use: During /arh-init when no stack is declared (empty stack list), before writing ADR-0001 § Decision.
user-invocable: false
allowed-tools: Read Grep Glob Bash
---
# Stack Selection

The stack list feeds `docs/adr/0001-tech-stack.md` § Decision — the exact section
`/arh-plan-implementation` gates on. When that list is empty (no stack was declared at
generate time), this is how it gets settled: **detect** it for a brownfield repo, or
**recommend** it for a greenfield one. Pick the branch from the greenfield/brownfield
verdict already established upstream — never both.

## Brownfield — detect, do not propose

The stack is already on disk. Read it; do not invent a target. Use [[codebase-exploration]]
for the *scan technique* (top-down, grep-before-read); this skill is the *map* — which
signal means which stack.

Detect→map table (deterministic — a present signal wins; ambiguity → confirm with the user,
never guess silently):

| Signal (present in repo)                     | framework            | package_manager        | test_runner (from devDeps/config) |
|----------------------------------------------|----------------------|------------------------|-----------------------------------|
| `package.json` + `next`                      | `nextjs`             | npm/pnpm/yarn (lockfile)| `vitest`/`jest`/`playwright`/`cypress` |
| `package.json` + `react` (no `next`)         | `react`              | npm/pnpm/yarn (lockfile)| `vitest`/`jest`                   |
| `package.json`, server (`express`/`fastify`) | that framework       | npm/pnpm/yarn (lockfile)| `vitest`/`jest`                   |
| `pyproject.toml`/`requirements.txt` + `fastapi`/`django`/`flask` | that framework | pip/poetry/uv (lockfile) | `pytest`             |
| `go.mod`                                     | `go`                 | go modules             | `go test` (`gotest`)              |
| `Cargo.toml`                                 | `cargo` (Rust)       | cargo                  | `cargo test`                      |
| `pom.xml` / `build.gradle`                   | `maven` / `gradle`   | maven / gradle         | `junit`                           |
| `*.csproj`                                   | `dotnet`             | nuget                  | `xunit`/`nunit`                   |

Rules:
- **Version** comes from the lockfile (resolved), not the manifest range. If only a range is
  pinned, record the range and note it.
- **package_manager** comes from the lockfile present (`package-lock.json`→npm,
  `pnpm-lock.yaml`→pnpm, `yarn.lock`→yarn, `poetry.lock`→poetry, `uv.lock`→uv, …).
- **test_runner** is inferred from a test dep or config file actually present. **No test tooling
  found → `none`** (the no-runner sentinel — do NOT invent one).
- A monorepo has **more than one** stack. Emit one row per detected manifest, each with its own
  `<id>`. Do not collapse them.
- Confidence is high when a framework dep is explicit. When a manifest exists but names no known
  framework, record what IS certain (language, package manager) and **confirm the framework with
  the user** before writing.

## Greenfield — recommend, then let the user choose

Nothing is on disk yet. Lead with a recommendation and its reason; the user confirms or
overrides. Drive the recommendation from what Phase 1 already gathered — **product type**
(Q1) and **primary language** (Q2) — plus personas and any NFR/compliance constraint. Do
**not** carry a hardcoded framework catalog; catalogs rot. Reason from these pinned criteria:

- **Web app, needs SSR / SEO / shared server+client** → an SSR framework (e.g. Next.js for a
  TS/React shop). SPA-only, no SEO need → a client framework (React/Vue) + a thin API.
- **API / backend service** → a server framework native to the primary language
  (FastAPI/Django for Python, Express/Fastify for TS, Spring for Java, Gin for Go).
- **CLI / library** → the language's standard tooling; no web framework.
- **Data / batch / automation** → the language's job/runner idiom, not a web server.
- **Heavy realtime / streaming** → note it explicitly; it changes D4 (execution model) and the
  framework choice.

Offer 1–3 concrete candidates, recommendation first, one line each — matching the
`04-architecture-decisions` phrasing so the two reads consistently:

```
recommended <framework> — because <product-type + language + constraint>.
Use this, or name another?
```

For each stack also settle `package_manager` and `test_runner` (recommend the language
default; `none` is allowed if the team defers tests). Keep it at *framework* altitude — not
library/schema choices, which emerge per feature in `/arh-plan-implementation`.

**Version — recommend a *line*, never a hardcoded number.** Nothing is installed yet, so there
is no resolved version to read. Recommend which release *line* to track — recommendation-first,
the user confirms — but never bake a version number into this skill (a number rots exactly like
a framework catalog would). The two lines:

- **latest-stable** — omit `version` entirely; the package manager resolves latest-stable at
  scaffold/install time. Default for greenfield speed, fast deploy cadence, no compliance lock.
- **current LTS** — the framework's long-term-support line. Bias here for regulated,
  long-lived, or conservatively-deployed projects. Ask the user for the exact LTS version to
  record — do not guess the number.

Parameters that drive the recommendation:

- **primary language runtime** (Q2) — caps which framework majors are compatible;
- **NFR / compliance** — a support-window or CVE-posture requirement → LTS;
- **deploy cadence / team maturity** — fast movers → latest-stable; conservative → LTS;
- **explicit user constraint** (compliance-locked runtime, existing-service compat) — overrides
  the recommendation; pin exactly to the value the user gives.

Phrase it like the framework recommendation:

```
recommended <latest-stable | current LTS> for <framework> — because <runtime / NFR / cadence>.
Use this, or name a specific version?
```

For latest-stable, omit `version` from the `harness.yaml` entry. For LTS or any pin, record the
exact version the user confirmed.

## Output — record the stack in harness.yaml, the source of truth

`harness.yaml stacks[]` is the **single source of truth** for the stack. The composer reads
it — never ADR-0001 — to synthesise the `<framework>-patterns` playbooks and wire them into
the agents' `skills:`. ADR-0001 § Decision is **derived** from `harness.yaml`, not authored
ahead of it. So the settled stack MUST be recorded in `harness.yaml`; writing only ADR-0001
would drift (ADR names a stack the composer never sees → no patterns, permanent divergence).

**Record it by editing `harness.yaml` directly.** Append one entry per settled stack under
`stacks:`, in the same structure the `harness init` wizard produces:

```yaml
stacks:
  - id: <id>                    # lowercase, hyphens; unique per stack
    framework: <framework>
    version: <version>          # omit for greenfield latest-stable (see Version rule)
    package_manager: <pm>       # omit if unknown
    test_runner: <runner>       # or `none` (the sentinel) when tests are deferred
    paths: ["**"]               # the stack's path globs; `**` for a single-stack repo
```

- **Brownfield:** one entry per detected manifest, with the resolved lockfile version.
- **Greenfield:** omit `version` for latest-stable; record `none` for `test_runner` when
  tests are deferred (write the literal `none` — do not leave the key absent).

Then write ADR-0001 § Decision from these entries — that unblocks `/arh-plan-implementation`
immediately (its gate reads § Decision), with no regenerate required.

**Wiring the `<framework>-patterns` playbooks — `harness generate`.** The per-stack playbook
skills are synthesised, and wired into the consuming agents' `skills:`, by the composer at
generate time. A runtime step cannot reproduce that wiring without hardcoding a
composer-derived list of agents that would silently drift — so this skill itself never edits
`.claude/agents/*` directly, only `harness.yaml`; wiring always happens through an actual
`harness generate` invocation:

```
harness generate
```

This synthesises each `<framework>-patterns` skill and wires it into the agents. **Safe to
re-run:** `*-patterns` skills are `preserve_on_regen` — an existing patterns skill the team has
already filled is never overwritten with a fresh TODO placeholder.

- **Brownfield** → `/arh-init` Phase 3 (`steps/03-folders.md`) runs this invocation itself,
  in-session, immediately after the stack settles into `harness.yaml` — before Phase 4/6 ever
  need the patterns files. Nothing further to do here.
- **Greenfield** → not run automatically. Tell the user to run it, once, after `/arh-init`
  completes. Until then, agents fall back to package-manager-native defaults (degraded, **not**
  blocked — the pipeline still runs on the ADR-recorded stack).
