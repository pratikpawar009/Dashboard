# PGD-01 — Agent flags

Raised during `/arh-implement` Step 1. Triage with `/arh-human-review PGD-01`.

### AF-01: tasks.json DAG is missing a `predecessors` edge T-09 ← T-10
status: accept (triaged 2026-09-04, /arh-implement Step 5 RC4)
raised_by: orchestrator (/arh-implement Step 1, round 2 scheduling)
T-09 (`ProgramDetailHeader`) renders `ProgramSwitcher` as a child per its own `tasks.json` notes
("switcher: ProgramSwitcher's own prop bundle"), so it has a compile-time import dependency on
T-10's F-18. `tasks.json` lists both with `predecessors: ["T-07"]` only, so the file-disjoint
batcher would have scheduled them in the same concurrent round and T-09's `tsc --noEmit` would
have failed on a module that did not exist yet. The orchestrator serialized T-09 behind T-10 by
hand. `plan-validation` § Cross-section consistency checks file-write conflicts but not
import-graph edges — a gap worth closing before the next feature plans a component tree.

### AF-02: ProgramSwitcher open-state border color is an implementation default, not a mockup value
status: accept (triaged 2026-09-04, /arh-implement Step 5 RC4)
raised_by: implementation-agent (T-10)
DESIGN.md Region 3 names `progBorder` and `caretTf` as open-state-derived client values but the
decoded mockup carries no literal color for the open-state trigger border. T-10 used `#2a6fdb`
(the same brand token as the row check-mark), documented inline in `ProgramSwitcher.module.css`.
This is the only pixel in the four regions not read byte-exact off the design source — confirm it
against the mockup or accept the default.

### AF-03: `tests/unit/test_auth_cors.py` edited but absent from the PLAN.md file plan
status: accept (triaged 2026-09-04, /arh-implement Step 5 RC4)
raised_by: orchestrator (/arh-implement Step 1, T-03)
D-07 adds `X-Program-Switch-From` to `CORSMiddleware.allow_headers`. An existing AUTH-01 test
asserted the literal `allow_headers` list, so it had to be updated in the same change — it
documents the contract D-07 alters. `tasks.json` `file_plan` has no `F-NN` entry for it (it lists
only `app/main.py` for T-03), so the file lands in the diff unplanned. Same class of gap as
AF-01: plan-validation checks write-conflicts between tasks, not which existing tests assert the
config a task is changing. Expected and correct here — confirm rather than revert.

### AF-04: `apps/web/.gitignore` blanket `.env*` silently dropped F-32
status: accept (triaged 2026-09-04, /arh-implement Step 5 RC4)
raised_by: implementation-agent (T-14), fixed by orchestrator
`apps/web/.gitignore:34` has `.env*` with no `!.env.example` exception. The root `.gitignore` has
that exception (line 42), but the nearer file wins, so `apps/web/.env.example` — a planned
deliverable (F-32) — existed on disk and was unstageable. `git check-ignore` confirmed it.
The orchestrator added `!.env.example` to `apps/web/.gitignore`; the file is now trackable.
That `.gitignore` line is a third file outside the PLAN.md file plan (cf. AF-01/AF-03) — confirm
it belongs in this diff. Worth asking whether the same shadowing hides other intended examples.

### AF-05: back-to-board link is not inside the sticky header, unlike the mockup
status: accept (triaged 2026-09-04, /arh-implement Step 5 RC4)
raised_by: implementation-agent (T-12)
DESIGN.md Region 1 anchors `BackToProgramBoard` at `<!-- HEADER -->` L389 as the **first child** of
the sticky header box, so in the mockup it stays pinned on scroll with the identity/switcher row.
T-08/T-09 shipped it as a standalone non-sticky component and T-12's composition renders it as a
sibling *above* the sticky header, so it scrolls away. The orchestrator dispatched a corrective
task to nest it inside the sticky wrapper (retained in the error state per D-03). Recorded here
because the plan's own §3 module tree lists the three regions flat, which is what invited the
mistake — the nesting lived only in DESIGN.md.

### AF-06: evidence-na — `design_check` dimension has no tool wired
status: accept (triaged 2026-09-04, /arh-implement Step 5 RC4)
raised_by: implementation-agent (evidence pass)
`docs/config/project-commands.yaml` `design_check:` is empty by design — no accessibility /
console-error-scan / perf tool is declared, and the html-mockup provider's `fileKey`/`url` are
still TODO in `docs/design/schema.json`. The evidence packet records design_check as N/A, matching
that file's own inline note. Please confirm the N/A, or wire a tool (e.g. axe-playwright, pa11y-ci)
against `apps/web`. This story is the first with a real rendered page, so the cost of the gap is
now non-zero.

### AF-07: evidence-na — runtime `render_check` unavailable (no E2E runner)
status: accept (triaged 2026-09-04, /arh-implement Step 5 RC4)
raised_by: implementation-agent (evidence pass)
`test_e2e` is empty and no Playwright/Cypress is installed, so the runtime dimension could not make
a formal browser assertion. The boot verdict stands on its own (HTTP 200 + clean boot log on both
stacks), and a curl of the SSR HTML for `/programs/prog-smoke-01` showed real rendered content —
"Back to program board" and the error-panel copy — rather than an empty mount node, so the residual
risk is low. Confirm the N/A or schedule an E2E runner.
