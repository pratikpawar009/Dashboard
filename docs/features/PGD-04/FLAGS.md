# PGD-04 — Agent flags

Raised during /arh-implement. Triage with `/arh-human-review PGD-04`.

### AF-01: F-10 shipped into programDetailApi.ts, not a new programCommandsApi.ts
- **Raised by:** T-11 (implementation-agent), 2026-09-17
- **Status:** resolved — FIXED 2026-09-17 (not accepted; the deviation was corrected)
- **What:** tasks.json F-10 specified creating `apps/web/src/lib/programCommandsApi.ts`. The
  orchestrator's task brief instead directed the function into the existing
  `apps/web/src/lib/programDetailApi.ts`, where `fetchProgramDetail` / `fetchPrograms` /
  `fetchProgramReleases` already live. The agent implemented as briefed and flagged the drift.
- **Why it is ambiguous:** the codebase is genuinely split on this, so neither location is wrong:
  - PGD-02 shipped a DEDICATED module — `apps/web/src/lib/programTokenTrendApi.ts` (+ `.client.ts`).
  - PGD-03 shipped into the SHARED module — `fetchProgramReleases` lives in `programDetailApi.ts`.
  PLAN.md's F-10 reason cites the PGD-02 precedent; the orchestrator's brief followed the PGD-03 one.
- **Resolution taken (2026-09-17):** **fixed to match the plan.** `fetchProgramCommands` +
  `FetchProgramCommandsOptions` were moved out of `apps/web/src/lib/programDetailApi.ts` into a
  new dedicated `apps/web/src/lib/programCommandsApi.ts`, exactly as F-10 specified, mirroring
  `programTokenTrendApi.ts`. The proxy route and its test now import from the new module, and the
  test's module docstring no longer references the deviation. Verified after the move: `tsc
  --noEmit` 0 errors, `pnpm -C apps/web test` 237/237 green, `eslint .` 0 errors.
- **Residual note for the engineer:** the codebase remains genuinely split — PGD-02/PGD-04 use
  dedicated modules, PGD-03's `fetchProgramReleases` still lives in the shared `programDetailApi.ts`.
  Worth deciding once (skill `decide`) so future frontend stories stop re-litigating it. Per
  `.claude/rules/pattern-consistency.md` that decision does NOT retroactively move PGD-03's file.

### AF-02: design_check — N/A as a TOOL run, DISCHARGED as a mockup-conformance check
- **Raised by:** evidence pass, 2026-09-17
- **Status:** resolved — FIXED 2026-09-17 (design obligation discharged by executable check)
- **Original finding:** `design_check:` is empty in `docs/config/project-commands.yaml` (no
  a11y / console-scan tool wired), so the dimension was marked N/A.
- **Why a tool run stays N/A, and is not the real gap:** axe / pa11y drive a browser against a
  URL. PGD-04 ships no rendered page — a JSON endpoint plus a server-only Next.js proxy Route
  Handler (REQUIREMENTS.md § Scope; no React component). There is nothing for such a tool to
  visit. Wiring one would also add a new dev dependency, contradicting T-14's verified
  no-config-drift result, and it belongs to whichever story first renders the panel.
- **The obligation that DOES apply, and how it was discharged:** CLAUDE.md § Design system binds
  backend stories too — an API story must "supply exactly what the mockup's bindings consume".
  That is now an executable check, not a claim:
  `services/api/tests/unit/test_program_commands_mockup_contract.py` (5 tests, green) asserts the
  response against `docs/design/mockups/Program Detail.html` § COMMANDS (decoded markup L507-539,
  generator L740-758):
  - the wire supplies exactly the bound fields (`cmdTotal` -> `total_runs`; `c.cmd`/`c.count`/
    `c.barStyle` -> `command`/`count`/`barStyle`), with no extras and none missing;
  - `barStyle` is max-of-range, matching the generator's `cmdCounts[i] / cmax` — with an explicit
    assertion that share-of-total would differ (it would render the leader at 30%, not 100%);
  - `command` keeps the leading slash the `<code>` chip renders (`'/' + c.cmd`);
  - `count` is numeric (it renders beside the literal "runs") while `total_runs` arrives
    display-ready for the 22px headline;
  - the empty state keeps `total_runs: "0"` so the headline binding never renders blank — D-02
    seen from the design side, and what `hint-placeholder-count="6"` implies (a canvas hint, not
    a row-count contract).
- **Mutation-verified:** the checks were confirmed to actually bite. Mutating the service to
  synthesize a leading slash (the `//arh-init` defect) failed 5 tests; the tree was restored and
  re-verified green (`git diff` empty, 14/14 pass).
- **For the engineer:** when a story first renders this panel, wire a real `design_check` tool
  then — that is where a browser-driven a11y scan earns its place.

### AF-03: carry-forward — ING-02 perf tests fail the p95 budget (NOT caused by PGD-04)
- **Raised by:** Step 2 entry gate, 2026-09-17
- **Status:** carry-forward — do NOT fix in this story
- **What:** `services/api/tests/perf/test_ingest_files_perf.py` (ING-02) has 3 `-m perf` cases
  failing their p95 budget (observed 4.0s / 3.9s against a 3.0s budget) on this machine.
- **Not PGD-04's:** the file is absent from PGD-04's diff (`git status --porcelain` confirms) and
  PGD-04's own perf suite passes 3/3 in isolation, re-verified 2026-09-17.
- **Why it is recorded here:** Step 1's evidence pass had folded this into PGD-04's own perf row as
  a hedged `"PASS (PGD-04 subset)"` with `exit_code: 1`. The reasoning was right but the shape was
  wrong — a qualified status string is not a literal the gate can evaluate, and burying another
  story's red inside this story's evidence is how a real failure gets normalised. The row is now a
  literal `PASS` scoped to PGD-04's own perf file, and the ING-02 failure lives here instead.
- **For the engineer:** belongs in the PR body's `## Carry-forward` section. Likely environment
  load (the whole `-m perf` selection runs against one Postgres), but it deserves its own look
  under ING-02, not a silent pass here.
