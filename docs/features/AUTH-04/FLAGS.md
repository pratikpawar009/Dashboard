# AUTH-04 — agent flags

Observations the implementation decided but wants a human to see. Triage via
`/arh-human-review AUTH-04`.

### AF-01: every `project-commands.yaml` command fails at its `pnpm` segment (pre-existing) · status: triaged — accepted

<!-- Triaged 2026-08-31 by Pratik Pawar during /arh-implement Step 1 flag triage: ACCEPTED as
     out-of-scope for AUTH-04. Pre-existing, unrelated to this feature (which adds zero frontend
     files), and the remedy is a supply-chain approval decision for a human. Carried forward to
     the PR body so it is fixed deliberately rather than silently. Does not block commit. -->

**Raised by**: evidence pass, `/arh-implement` Step 1.

Each canonical command (`typecheck`, `test`, `lint`, `build`) begins with `pnpm -C apps/web …`.
`pnpm` runs a deps check that shells out to `pnpm install`, which exits 1:

```
[ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: unrs-resolver@1.12.2
Run "pnpm approve-builds" to pick which dependencies should be allowed to run scripts.
[ERROR] Command failed with exit code 1: pnpm install
```

So the composite commands cannot complete as written, regardless of code quality. The tools
themselves are healthy — run directly from `apps/web/node_modules/.bin`, `tsc --noEmit`,
`eslint .`, `vitest run`, and `next build` all exit 0, which is how this feature's evidence was
gathered.

**Pre-existing and unrelated to AUTH-04**, which adds zero frontend files. Not fixed here for two
reasons: `.claude/rules/surgical-changes.md` forbids fixing adjacent unrelated breakage, and the
remedy (`pnpm approve-builds`, or an `onlyBuiltDependencies` entry in `apps/web/package.json`) is
a **supply-chain approval decision that belongs to a human** — an agent should not silently grant
a package permission to run install scripts.

**Suggested action**: decide on `unrs-resolver@1.12.2` and record the approval in
`apps/web/package.json`, so `docs/config/project-commands.yaml` becomes runnable as written.

### AF-02: `design_check` dimension is N/A — no tool wired · status: triaged — accepted

<!-- Triaged 2026-08-31 by Pratik Pawar during /arh-implement Step 1 flag triage: N/A CONFIRMED on
     both grounds (no design_check tool wired in project-commands.yaml; AUTH-04 is backend-only
     with design='n/a'). Same disposition as BED-01 AF-09 and AUTH-03 AF-02. Does not block commit. -->

**Raised by**: evidence pass, `/arh-implement` Step 1.

`docs/config/project-commands.yaml` has `design_check: ""` — no accessibility / console-error /
perf tool has been chosen or installed for this project (the file says so explicitly, and notes
`/arh-implement` will raise an `evidence-na` flag until one is wired). Independently, AUTH-04 is
backend-only (`state.json design: "n/a"`, no AUTH entry in `docs/design/schema.json`), so there is
no UI surface for such a tool to inspect even if one existed.

N/A on both grounds. Same disposition as BED-01 (AF-09) and AUTH-03 (AF-02).

**Suggested action**: confirm the N/A, or wire a tool (e.g. `axe-playwright`, `pa11y-ci`) into
`design_check` before the first story that ships UI.
