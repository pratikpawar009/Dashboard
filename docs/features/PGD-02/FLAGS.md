# PGD-02 — Flags

## Carry-forward (pre-existing, NOT caused by PGD-02)

- `services/api/tests/perf/test_rollup_rebuild_perf.py::test_org_rebuild_budget_and_growth_curve`
  fails on a pristine `origin/main` tree. Verified by stashing all PGD-02 work and running
  `uv run pytest tests/perf tests/test_migrations.py -q` on the clean checkout:
  `1 failed, 43 passed`. Unrelated to this feature — record in the PR `## Carry-forward`
  section, do not fix here (`.claude/rules/surgical-changes.md`).

## F-01 — Proxy collapses a backend 400 into 502 (accepted, not fixed)

Raised by the T-10 worker. `fetchProgramTokenTrend()`
(`apps/web/src/lib/programTokenTrendApi.ts`) maps any non-404/401 non-2xx response to
`{status: "error"}`, which the proxy Route Handler renders as `502 upstream_error`. So a
backend `400 invalid_range` does not survive the proxy hop as a 400.

**Decision: accepted as-is, deliberately not fixed in PGD-02.**

- AC-6 and its tests (TC-12, TC-13) specify the **FastAPI route**, not the proxy — their steps
  send `GET /api/overview/program-detail/{id}/token-trend?range=15d` directly. Both are
  covered and passing in `tests/unit/test_program_token_trend_route.py`.
- The 4-state union (`ok | not_found | unauthorized | error`) is the shipped PGD-01 sibling's
  own vocabulary (`apps/web/src/types/programDetail.ts:63-66`). Adding a fifth `bad_request`
  variant here would fork the convention for one endpoint
  (`.claude/rules/pattern-consistency.md`, `.claude/rules/reusability-baseline.md`).
- Not reachable from the UI: the client module only ever sends a value from the 7D/30D/90D
  toggle, so a malformed `range` cannot originate in the browser.

**Carry-forward**: if a future story needs 400 passthrough on the proxy tier, the fix belongs
at the shared `ProgramDetailResult`/`ProgramTokenTrendResult` union so PGD-01 and PGD-02 move
together — not as a PGD-02-local special case.

## F-02 — authFlow test needed the new client module mocked (fixed in-scope)

Raised independently by the T-13, T-14 and T-15 workers. Mounting the self-fetching
`DailyTokenTrendChart` (T-13) broke
`apps/web/src/components/ProgramDetailView.authFlow.test.tsx` step 6, which asserts no real
browser request leaves jsdom. That file mocked `@/lib/programDetailApi.client` but not the
new `@/lib/programTokenTrendApi.client`, so the chart's real fetch escaped and tripped
`expect(fetchMock).not.toHaveBeenCalled()`.

**Fixed by the orchestrator** (no worker owned that file): added the missing
`vi.mock("@/lib/programTokenTrendApi.client", ...)` alongside the existing one, and folded
the new mock's calls into the same token-leak assertion so the check now covers the chart's
calls too rather than merely ignoring them. The mock resolves an `ok` result because the
component calls `.then()` on it directly.

This was a regression caused by PGD-02's own wiring, not pre-existing drift — so it is fixed
here rather than carried forward. Full suite: 206/206 green.

## F-03 — `test_no_duplicate_frontend_formatter_exists` needed a documented exception for D-04 (fixed in-scope)

Raised by the evidence pass, round 1. `services/api/tests/unit/test_format.py`'s generic
K/M-suffix heuristic (BED-02-TC-13) flagged `DailyTokenTrendChart.tsx`'s `formatTokens()` as a
suspected duplicate frontend formatter. Root cause: the heuristic predates PGD-02 D-04
(`docs/features/PGD-02/DECISIONS.md`), a documented, reasoned exception — the mockup's own
`fmtM` mislabels a raw token count by ~6 orders of magnitude (1,200 -> "1.20B"), so
`formatTokens` reconciles a new threshold ladder scoped to that one component.

**Fixed in-scope**: added a named, documented allowlist
(`_ALLOWED_SUFFIX_MATCH_FILES = {"DailyTokenTrendChart.tsx"}`) to the suffix-heuristic branch
only. The `_FORBIDDEN_PATTERNS` identifier check — the check that actually catches a
*rediscovered* `formatNumber`/`formatMK`/etc. — is untouched and remains fully strict for
every file, including this one. `test_format.py`: 31/31 passing after the fix.

### AF-01: evidence-na · task: n/a · docs/config/project-commands.yaml

`design_check` dimension marked N/A — `project-commands.yaml`'s `design_check:` key is empty
by design: no accessibility/console-error-scan/perf tool has been chosen or wired for this
project yet (see the file's own comment). Not specific to PGD-02.
