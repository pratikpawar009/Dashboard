# Code Review — feature/SHP-04

- Date: 2026-09-18
- Mode: story (GATE MODE — report-only)
- Files reviewed: 15 (+ tasks.json/state.json/DECISIONS.md/etc. read for context, not counted as diff)
- Verdict: PASS WITH WARNINGS

## Executive summary

SHP-04 adds `GET /api/artifacts/{program_id}` (5-row fixed-order artifact counts, server-owned
presentation constants) plus a standalone, unwired `ArtifactsPanel` frontend component. The RBAC
gate (`governance_visibility`'s first live route consumer) is wired exactly per D-02/FR-2/FR-3,
and the test suite genuinely proves the cio/engineering-manager exclusion via a query spy showing
zero `program_artifacts` SELECTs on denial, plus self-witnessing log assertions that guard against
the known Alembic-`fileConfig`-disables-loggers trap. Zero-fill correctness (AC-3/AC-4 parity) is
exercised end-to-end (TC-06/07/08). All 15 files trace 1:1 to `tasks.json` `file_plan` F-01..F-16
— no scope creep. The `artifacts-api` contract in `docs/requirements/api.md` was updated in the
same diff (D-05), matching the shipped code exactly. One judgement call flagged below (proxy
403→502 mapping) as a warning, not a blocker, since it mirrors an existing shipped precedent
faithfully and is test-documented rather than silently introduced.

🟢 RBAC gate correctly ordered, first-live-consumer risk retired with real coverage; zero-fill via single `.get()` code path, no special-casing; presentation constants correctly server-owned throughout the stack; contract doc updated in-diff; zero scope creep.
⚠️ 403 governance denial surfaces to the browser as a generic 502 upstream error, indistinguishable from a real backend outage; five-tag-chip/colour constants duplicated across 3 files (service table + tokens.md + DESIGN.md) with no single source of truth beyond convention.
🛑 None.

## Findings summary

| Severity | Count | Category distribution                                    |
|----------|-------|-----------------------------------------------------------|
| CRITICAL |   0   | —                                                           |
| HIGH     |   0   | —                                                           |
| MEDIUM   |   2   | integration (1), design-patterns (1)                       |
| LOW      |   1   | testability (1)                                             |

## Detailed findings

### MEDIUM

#### F-1 — integration: 403 governance denial surfaces as an opaque 502 to the browser
- Category: integration
- Path: `apps/web/src/app/api/proxy/artifacts/[program_id]/route.ts:26-30,59`
- Source: `.claude/rules/performance-baseline.md` (no rule directly on point) / judgement call requested by reviewer
- Description: `ArtifactsResult` has no `forbidden` variant, so `fetchProgramArtifacts()`'s generic non-ok branch folds a legitimate `governance_visibility` 403 into `{status: "error"}`, and the proxy emits `502 upstream_error`. This is faithful to the `team` proxy precedent (verified: `team/route.ts` does the same fold) and is explicitly documented in both the route docstring and a dedicated test (`route.test.ts` — "surfaces a FastAPI 403 governance denial as 502... not a 403"). The judgement call: a `cio`/`engineering-manager` viewer hitting this proxy sees "upstream failure," not "you don't have access" — worse UX/observability than a true `forbidden` status would give, and on-call could misdiagnose a spike of 502s from denied personas as a real FastAPI outage. Because SHP-04 explicitly ships the component unwired (D-04), no real user hits this path yet — the blast radius today is zero, and the pattern is inherited, not invented, so this does not block the gate.
- Suggested fix: Not required to unblock. When ARC-01/DEV-01/PMD-01 wire the panel in, consider promoting this to an ADR-level decision (add a `forbidden` variant to the shared `*Result` unions, or accept 502-for-403 permanently as a documented convention) rather than let each new proxy silently re-inherit an increasingly load-bearing shortcut. Track as carry-forward, not a fix-now item.

#### F-2 — design-patterns: five tag/colour presentation constants duplicated in 3 places
- Category: design-patterns
- Path: `services/api/app/services/artifacts.py:34-40`, `docs/design/tokens.md` § Artifact tag-chip colors, `docs/features/SHP-04/DESIGN.md` § Presentation constants
- Source: `.claude/rules/reusability-baseline.md` ("DRY across modules of the same concern")
- Description: The 5 `(tag, name, bg, color)` pairs are transcribed by hand into the service module's `_ARTIFACT_PRESENTATION` tuple, `tokens.md`'s new "Artifact tag-chip colors" table, and `DESIGN.md`. This matches the established `_BOARD_METRIC_GLYPHS_LABELS`/`_ORG_SUMMARY_GLYPHS_LABELS` idiom (D-03 cites this precedent explicitly), where `tokens.md` documents a value that a Python constant actually owns at runtime — so this is consistent with how the codebase already handles every other server-owned-constant table (ADR-0007/0009 precedent), not a new drift risk SHP-04 introduces. The residual risk is generic to the pattern: if any of the 3 copies is edited without the others, nothing catches the divergence (no test asserts `tokens.md`'s table matches `_ARTIFACT_PRESENTATION` byte-for-byte).
- Suggested fix: Acceptable as shipped — matches codebase convention. If this class of drift becomes a repeat pain point (four such tables now: board, org-summary, program-detail summary, artifacts), consider a lint/test that diffs the Python constant against its `tokens.md` transcription, but that is a cross-cutting improvement, not SHP-04-scoped.

### LOW

#### F-3 — testability: `_CANONICAL_ARTIFACT_TYPES` vocabulary duplicated as an ordered tuple
- Category: testability / design-patterns
- Path: `services/api/app/services/artifacts.py:34-40`
- Source: `REQUIREMENTS.md` SHP-04-FR-1 (explicitly calls this out as a known tradeoff)
- Description: `app/schemas/ingest_artifacts.py::_CANONICAL_ARTIFACT_TYPES` is an unordered `frozenset`; `artifacts.py` restates the 5 types as an ordered tuple because SHP-04-FR-1 requires a fixed wire order the frozenset can't express. REQUIREMENTS.md already flags this as deliberate, not an oversight. If a 6th canonical artifact type is ever added to the frozenset, `_ARTIFACT_PRESENTATION` will not pick it up automatically — the two vocabularies silently diverge (the frozenset would have 6 entries, the response would still show 5) with no test to catch it, since both files currently hard-code 5 entries and no test cross-checks set membership between them.
- Suggested fix: Not blocking — no test currently asserts `len(_ARTIFACT_PRESENTATION) == len(_CANONICAL_ARTIFACT_TYPES)` or that their canonical-type sets are equal. A cheap one-line unit test doing that comparison would catch future drift for near-zero cost; worth a follow-up task, not a gate blocker.

## What went well

- The RBAC gate's first-live-consumer risk (R-03) is retired with real, high-value coverage: TC-03's query spy proves zero `program_artifacts` SELECTs on denial for BOTH excluded personas, and TC-04's self-witnessing log assertion (asserting the authorized emission before asserting the denial-event absence) defends specifically against the known Alembic `fileConfig` logger-disabling trap this codebase has been bitten by before.
- Zero-fill (AC-3/AC-4) is implemented via one `.get(canonical_type, 0)` lookup with no special-casing between "missing row" and "real zero row" — exactly as D-03 specifies — and both cases are independently tested (TC-07 vs TC-08) rather than assumed identical.
- `count` is a raw int end-to-end (schema `Field(...)`, TS `count: number`, component renders via `String(item.count)` for display only); `bg`/`color`/`tag`/`name` are server-owned everywhere checked (Pydantic model, TS types, component inline styles) — no client-side derivation crept in.
- `docs/requirements/api.md`'s `artifacts-api` contract was updated in the same diff (D-05) and its wire shape matches the shipped Pydantic model and service constants exactly — no contract-drift.
- File-plan discipline is exact: all 15 in-scope files map 1:1 to `tasks.json` F-01..F-16; `dev-login/` and `mcp-server/uv.lock` correctly excluded as pre-existing/unrelated. `ArtifactsPanel` is confirmed unwired (no page imports it), matching D-04/Scope Out precisely.

## Recommendation

PASS WITH WARNINGS. No CRITICAL or HIGH findings; 2 MEDIUM findings, both judgement calls on inherited patterns rather than defects introduced by this diff, plus 1 LOW. Ship as-is. Carry forward F-1 (403→502 proxy mapping) for consideration when ARC-01/DEV-01/PMD-01 wire the panel into real pages, and F-3 (frozenset/tuple vocabulary drift guard) as a cheap follow-up test.
