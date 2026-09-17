
### AF-01: Pre-existing order-dependent test failure in test_admin_repo_scan.py
- **Raised by**: T-01 (implementation-agent)
- **Status**: open
- **Observation**: `uv run pytest -q --ignore=tests/perf` shows `1 failed, 734 passed` —
  a failure in `tests/test_admin_repo_scan.py` plus related `TestSchemaDiffGate` errors.
- **Verified pre-existing**: the agent stashed its T-01 changes and reproduced an identical
  failure count on the pre-T-01 baseline, so this is not caused by PGD-05.
- **Suspected cause**: DB-state pollution / test isolation, not a product defect.
- **Action**: carry-forward to the PR body; do NOT inline-fix (surgical-changes rule).

### AF-02: Shared test-Postgres isolation flakiness in the `migrated_db` fixture
- **Raised by**: T-06 (implementation-agent); independently corroborated by T-01 and T-03
- **Status**: open
- **Observation**: repeated back-to-back runs of any single service-level test file
  intermittently fail with `UniqueViolation: pg_type_typname_nsp_index already exists` or
  `UndefinedTable: relation "usage_events" does not exist` during the function-scoped
  `upgrade head` / `downgrade base` cycle in `services/api/tests/conftest.py`.
  Full-suite runs show failures/errors in `test_mint_ingest_token.py`,
  `test_rollup_rebuild_*.py`, `test_admin_repo_scan.py`, `test_freshness.py`.
- **Verified pre-existing**: reproduced identically against already-shipped sibling test
  files and against the pre-T-01 baseline. Not caused by PGD-05.
- **Isolated runs are green**: PGD-05's own files pass consistently in isolation
  (T-06: 9/9; T-03: 54/54 across the sibling route tests).
- **Action**: carry-forward to the PR body; do NOT inline-fix (surgical-changes rule).
  Supersedes the narrower AF-01 observation.

### AF-03: DECISIONS.md D-04 names a `fetch_personal_usage()` that does not exist
- **Raised by**: orchestrator, from T-04's implementation note
- **Status**: open
- **Observation**: D-04 (and tasks.json T-04's notes) say the popup route "calls
  `fetch_personal_usage()`" as though SHP-02 exposed one function. It does not.
  `services/api/app/services/personal_usage.py` exposes three: `fetch_card_totals`,
  `fetch_daily_token_series`, `fetch_commands_breakdown` (verified at lines 74/116/167),
  which is exactly what SHP-02's own route composes.
- **Resolution taken**: T-04 followed the real shipped contract and called all three,
  returning `PersonalUsageResponse` verbatim per AC-10. The decision's *intent* — reuse
  SHP-02's service layer directly, never an HTTP hop, zero edits to SHP-02 — is satisfied.
- **Why flagged anyway**: DECISIONS.md is a binding artifact; its shorthand is now known to
  be imprecise, and a future reader could take it literally. Worth a one-line correction to
  D-04 so the log matches the code.
- **Action**: engineer decision at triage — correct D-04's wording, or accept as-is.

### AF-04: T-15 created two files the plan's F-NN file list did not name
- **Raised by**: orchestrator, from T-15's implementation note
- **Status**: open
- **Observation**: T-15 shipped two files beyond its planned `files[]`:
  1. `apps/web/src/components/ProgramTeamPanel.module.css` — every sibling component in
     `apps/web/src/components/` has a colocated CSS module; the plan's file list omitted one.
     Pre-authorised by the orchestrator's task brief as in-scope wiring.
  2. `apps/web/src/lib/programTeamApi.client.ts` — NOT pre-authorised. Root cause given:
     inlining `fetch` in the component broke `ProgramDetailView.authFlow.test.tsx`'s
     no-token-leak assertion, because that test mocks one `@/lib/*Api.client.ts` seam per
     self-fetching panel. The agent extracted the fetch to match the shipped
     `fetchProgramReleases` / `fetchProgramTokenTrend` pattern.
- **Also modified outside scope**: `apps/web/src/components/ProgramDetailView.authFlow.test.tsx`
  (added the new client mock + its `allClientCallArgs` entry), following the documented
  precedent already present there for PGD-02/PGD-03.
- **Note**: T-12 had already created `apps/web/src/lib/programTeamApi.ts` (the server-only
  fetcher). The codebase now has both a server and a client fetcher for this endpoint, which
  matches sibling precedent but is worth an explicit look at triage.
- **Action**: engineer decision — confirm the two additions are wanted, or fold them back.

### AF-05: `daily_tokens.points[].value` is a pre-formatted string — the popup chart cannot plot it
- **Raised by**: ux-agent (design iteration 1), DESIGN.md § 2.9
- **Status**: open — BLOCKS T-16's chart block only
- **Verified**: `services/api/app/schemas/personal_usage.py:43` — `DailyTokenPoint.value: str`
  ("Pre-formatted token total for this day", e.g. "4.2M"), locked by ADR-0009 as SHP-02's
  shipped contract. `DailyTokenSeries.period_total` / `avg_per_day` are likewise `str`.
- **Conflict**: `DailyTokenTrendChart` (PGD-02) was built against RAW ints and plots numbers.
  AC-10 requires the popup render `personal-usage-api`'s response verbatim — but a chart
  cannot plot "4.2M" without recovering a number from it.
- **Options**: (a) renderer parses magnitude suffixes back to numbers — lossy and fragile;
  (b) the `/team/{member_id}/usage` route supplies a raw series alongside the formatted one —
  but that breaks "verbatim" (AC-10); (c) amend SHP-02's contract to carry both a raw and a
  formatted value — touches a shipped, security-reviewed story.
- **Unaffected**: the cards row and commands list are fully buildable now. Trigger, modal
  chrome and all four states are fully specified and need no further design input.
- **Action**: contract decision required before T-16's chart block ships.

**2026-09-17 decision (user)**: build T-16 WITHOUT the chart block. Trigger, modal chrome,
all four states, the cards row and the commands list ship now; the daily-tokens chart is
deferred until the contract question above is decided. T-16 therefore satisfies AC-9, AC-11
and AC-12 in full, and AC-10 partially — the popup renders `personal-usage-api`'s cards and
commands verbatim, but omits the chart block. Recorded as a known, deliberate gap.

### AF-06: Planning artifacts still describe the pre-D-06 5-field row shape
- **Raised by**: Q-01 fix agent
- **Status**: open (documentation consistency, no code impact)
- **Observation**: `docs/research/PGD-05.md`, `docs/features/PGD-05/REQUIREMENTS.md`,
  `docs/features/PGD-05/DATA-DESIGN.md` and `docs/stories/PGD-05.md` still show
  `ProgramTeamRow` as 5 fields in prose. The authoritative contracts
  (`docs/requirements/api.md`, `README.md`, the schema itself) are correct at 6.
- **Assessment**: research and the story are historical records of what was known at the time
  — arguably correct to leave. REQUIREMENTS.md § FR-2 and DATA-DESIGN.md are live specs and
  are the two worth reconciling.
- **Action**: engineer decision at triage.

---

## Triage 2026-09-17

### AF-01 / AF-02 — TRIAGED: no defect. Diagnosis was wrong; corrected here.
**Disposition**: carry-forward only, no code change.

A dedicated investigation (two clean sequential `uv run pytest tests/` runs on an idle machine,
`HARNESS_TEST_DB_SUFFIX`/`TEST_DATABASE_URL` unset) produced **795 passed, zero
`UniqueViolation`, zero `UndefinedTable`**, and every file named in AF-01/AF-02 passed.

Root cause of the original reports: **this session's own parallel implementation agents each ran
pytest against the shared `dashboard_test` database simultaneously.** `migrated_db` is
function-scoped (`services/api/tests/conftest.py:260-272`) and runs `upgrade head` / `downgrade
base` around every test, so a second process's teardown drops the schema the first is mid-test
against. `conftest.py:84-115` already documents this exact incident (AF-11, ING-10, triaged
2026-09-08) and ships `HARNESS_TEST_DB_SUFFIX` as the standing mitigation. No parallel runner is
configured (pytest-xdist is not installed).

**Standing mitigation**: set `HARNESS_TEST_DB_SUFFIX=<agent-id>` whenever concurrent agents run
pytest. Nothing to fix in committed code.

### AF-05 — deferred chart block (see separate decision below)

### AF-06 — TRIAGED: resolved.
All four documents reconciled to the shipped 6-field `ProgramTeamRow`. REQUIREMENTS.md (FR-2,
C-4) and DATA-DESIGN.md corrected in place; `docs/research/PGD-05.md` and
`docs/stories/PGD-05.md` received appended dated notes (historical records, not rewritten).

### AF-03 — TRIAGED: resolved.
DECISIONS.md D-04 no longer references a nonexistent `fetch_personal_usage()`; it now names the
three real service functions.

### AF-04 — TRIAGED: closed, no action.
The server + `.client` fetcher pair matches shipped precedent — `programDetailApi` and
`programTokenTrendApi` both have exactly this shape. `ProgramTeamPanel.module.css` matches every
sibling component. Both additions are correct.

### NEW CARRY-FORWARD (pre-existing, NOT PGD-05's, do not fix here)
`services/api/tests/perf/test_rollup_rebuild_perf.py::test_org_rebuild_budget_and_growth_curve`
fails reproducibly on the committed baseline: `assert 8.356 <= 8.0` (`_ORG_GROWTH_MAX_RATIO`,
`:99`). Both absolute budgets pass; only the large/small p95 ratio exceeds, by 4.5%. It passes
in isolation and fails in a full suite — a wall-clock ratio assertion sensitive to cache warmth
over a 3.5-minute run. It also carries no `@pytest.mark.perf` (`:188`), unlike 5 of the 20 files
in `tests/perf/`, so `addopts = "-m 'not perf'"` does not deselect it and it runs in every
default suite. Belongs to BED-05's owner. User decision 2026-09-17: carry-forward, do not touch —
the budget constant's own comment says "Do not relax this budget — investigate the regression."

### AF-05 — TRIAGED: resolved. Chart block now ships.
**Disposition**: fixed (user decision 2026-09-17, option "add raw to DailyTokenPoint").

`DailyTokenPoint.tokens: int` added alongside the unchanged `value: str` — additive, no existing
consumer breaks. Extends ADR-0009's OWN precedent: `commands[].count` was already documented
there as "the one deliberate exception ... since it is the bar formula's own input", and a chart
series is the same category of value. Field name mirrors `ProgramTokenPoint.tokens` (PGD-02),
which uses the identical name for the identical role.

Verified (orchestrator, not taken on trust):
- `services/api/app/schemas/personal_usage.py` — `value: str` still present; `tokens: int` added.
- `services/api/app/services/personal_usage.py:116` —
  `value=format_number(day_total), tokens=day_total`: both derive from the same int, so the raw
  value is never recovered by parsing the formatted string.
- `services/api/tests/unit/test_personal_usage.py:313` —
  `test_daily_token_points_raw_and_formatted_agree` asserts `value == format_number(tokens)`
  across a 30-day K/M-magnitude series. Drift guard in place.

ADR-0009 received a dated `## Amendment (2026-09-17)` section; its original decision text was not
rewritten. `docs/requirements/api.md` and `README.md` updated (the README's "commands[].count is
a raw int, every other value pre-formatted" line was made false by this change and was corrected).

`DailyTokenTrendChart.tsx`'s previously-private `TokenAreaChart` was extracted and exported with a
`height` prop (default 240, so the existing Program Detail mount is visually unchanged); the popup
reuses it at 180px per DESIGN.md § 2.3 rather than carrying a second chart implementation.

**Denied (403) state still renders NO chart scaffolding** — the § 2.5 hard rule holds, asserted
explicitly in the extended denied-state test (no chart title, no `<svg>`, no skeletons).

**AC-10 is now fully met**: the popup renders `personal-usage-api`'s cards, daily-tokens chart and
commands. The earlier "partially met" note is superseded.

### AF-07: Frontend runtime evidence is boot-only — no browser render check
- **Raised by**: evidence pass (runtime dimension)
- **Status**: open (evidence-na, awaiting engineer confirm)
- **Observation**: the Next.js stack's runtime evidence is `200 + clean boot log` only.
  `render_check: "unavailable"` — no Playwright-driven assertion that the app actually mounted.
  A client-rendered app serves 200 with an empty mount node, so boot alone is weak evidence.
- **Why**: `docs/config/project-commands.yaml` defers Playwright execution to
  `/arh-validate-feature` (needs a running API + seeded data); no browser binaries here.
- **Action**: engineer eyeballs the running app at `/arh-human-review`, or accepts that
  `/arh-validate-feature` supplies the render evidence.

### AF-08: `design_check` dimension is N/A — no tool wired
- **Raised by**: evidence pass (design_check dimension)
- **Status**: open (evidence-na, awaiting engineer confirm)
- **Observation**: `docs/config/project-commands.yaml` leaves `design_check:` deliberately empty,
  with a comment explaining no a11y/console-error-scan/perf tool has been chosen yet.
- **Relevance to PGD-05**: this story ships real UI (team table + popup) with explicit WCAG AA
  obligations (NFR-008) — accessible row-trigger name, keyboard operability, dialog semantics.
  Those are covered by unit assertions in ProgramTeamPanel.test.tsx / MemberUsagePopup.test.tsx,
  but by no automated a11y scan.
- **Action**: engineer confirms N/A, or wires a tool (e.g. axe-playwright, pa11y-ci).
