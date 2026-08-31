# Code Review — feature/AUTH-04

- Date: 2026-08-31T14:00:00Z
- Mode: current (gate — `/arh-implement` Validate ∥ Review)
- Files reviewed: 8 (5 source, 2 test, 1 docs) + ADR-0005 + `docs/requirements/api.md` contract
- Verdict: **PASS**

## Executive summary

`GET /api/programs` implements the ADR-0005 switcher-list shape exactly, scopes strictly server-side, and closes all five carried-forward research conditions (C-1 PII allowlist, C-2 veto-gate call-once, C-3 fail-closed subclass-first, C-4 perf baseline, C-5 defensive filtering). Verified directly, not just read: `uv run pytest tests/unit/test_programs.py tests/perf/test_programs_perf.py` → 18/18 pass (p95 measured under the 300ms budget); `ruff check` and `mypy` clean on every changed file; a SAST grep of the diff found no hits. The `docs/requirements/api.md#programs-api` contract was updated in the same diff — no contract-drift. Both AUTH-04 planning decisions (D-01 palette function, D-02 router path) are honored in code exactly as recorded, and ADR-0005's field set/exclusions are implemented and contract-tested (TC-06 asserts key-set equality, not a subset).

🟢 strengths: full condition coverage, real end-to-end perf test (not mocked DB), single-veto-gate call verified by spy, PII allowlist verified by log-capture, fail-closed error path verified with a wall-clock bound.
⚠️ warnings: one LOW naming deviation from PLAN.md's literal-field-name instruction (functionally inert, contract-tested, no risk).
🛑 blockers: none.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 0 | — |
| LOW | 1 | design-patterns (1) |

## Detailed findings

### LOW

#### F-1 — design-patterns: `ProgramEntry.dotStyle` implemented as aliased `dot_style`, not the literal field name PLAN.md specified
- Category: design-patterns
- Path: `services/api/app/schemas/programs.py:21-25`
- Source: `docs/features/AUTH-04/PLAN.md` § Module Hierarchy — "field literally named `dotStyle`, not `dot_style` — matches the mockup binding + ADR-0005's exact key set, TC-06"
- Description: PLAN.md explicitly directs a Python field literally named `dotStyle`. The implementation instead declares `dot_style: str = Field(..., alias="dotStyle")` with `populate_by_name=True`. Verified this is wire-compatible: FastAPI's `response_model_by_alias` defaults to `True`, so the serialized JSON key is `dotStyle` regardless (confirmed with a standalone `TestClient` round-trip and by `test_programs.py::test_program_entry_key_set_matches_adr_0005_exactly_tc06` passing). No behavioral or contract impact; arguably more idiomatic than the plan's literal instruction since every other field in this codebase's Pydantic schemas is snake_case Python with camelCase reserved for the wire alias where needed.
- Suggested fix: none required to merge. If PLAN.md's literal instruction matters going forward (e.g., an ADR later mandates no-alias schemas), record that as a decision; otherwise no action needed — this is documented here only because the plan was explicit and the code diverges from it.

## What went well

- ADR-0005 field set (`program_id, label, href, dotStyle`) implemented exactly; `type`/`description` correctly absent, `current`/`rowStyle` correctly never modeled server-side.
- FR-2/C-2: `program_visibility` called exactly once via a documented sentinel `program_id` that is provably never read for scoping — verified by call-recording spy (TC-11, `len(visibility_calls) == 1` against 5 seeded programs).
- FR-3/C-3: `PersonaNotFoundError` caught before its own base class `PersonaResolutionError` (mirrors `app/core/rbac.py`'s established order); both branches log WARNING and return `HTTPException(403, "Access denied")`, never 500 — verified including a wall-clock-bounded mocked-timeout case (TC-14).
- FR-1/C-1: `programs_list_returned` log payload verified by log-capture to be the exact `{user_id, persona, returned_count}` allowlist (plus `JSONFormatter`'s `timestamp`) — no email, groups, or request path (TC-10).
- FR-4/C-5: missing-program discrepancy silently filtered by the WHERE clause and separately WARN-logged only on the non-cio path (TC-15/16); correctly not compared on the `cio` path where `returned_count` is the full table size.
- NFR-security: client-supplied `?programs=` query string proven ignored — scoping is derived solely from `current_user.programs` (TC-18).
- No pagination is correctly treated as an intentional, already-accepted PRD Scope decision (research risk #7, condition-free) — not flagged as a performance-baseline gap, per the review brief.
- `docs/requirements/api.md#programs-api` contract updated in the same diff (fields/authority/excluded/client_derived) — no contract-drift.
- `get_persona_resolver` added to `persona_resolver.py` rather than reusing `rbac.py`'s private `_resolver()` — correct boundary discipline (reusability-baseline: no coupling unrelated modules to share code).
- File set matches `tasks.json` `file_plan` F-01..F-08 exactly; no out-of-scope edits found (docs/adr/README.md and docs/stories/AUTH-04.md changes are the expected ADR-index registration and traceability-header update, not scope creep).
- Live verification: `pytest` 18/18 pass, `ruff check` clean, `mypy` clean, zero SAST hits on the diff.

## Recommendation

**PASS.** No CRITICAL/HIGH/MEDIUM findings; one informational LOW that does not affect behavior or contract. No fix pass required before merge.
