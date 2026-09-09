# AUTH-06 — Decisions

Decision log for roster-sourced program membership. The overarching architectural choice
(program membership comes from `program_roster`, never Keycloak `groups`) is a standing project
boundary the user set 2026-09-08 and REQUIREMENTS.md/the story's own Decision log already record
it — not re-litigated here. The four entries below are planning-time decisions this phase makes.

### D-01: `get_current_user` takes the roster DB session as its own `Depends(get_db)` parameter, not a resolver-owned `session_factory` · blast:feature · rev:mechanical · adr:—

**Context**: `PersonaResolver` (AUTH-02, the pattern FR-2 says to mirror) owns an injectable
`session_factory` internally, defaulting to `SessionLocal`, because it is invoked ad hoc from
whichever route opts into `Depends(get_persona_resolver)`. `ProgramRosterResolver.resolve()` is
different: it runs on the CRITICAL PATH of every non-dev-bypass `get_current_user` call, the
dependency every authenticated route shares. Auditing existing test files (`test_overview.py`,
`test_personal_usage.py`, `test_programs.py`, `test_ingest_token_isolation.py`) shows every one
that needs a disposable test database already does so via
`app.dependency_overrides[get_db] = <test-session override>` — a resolver-owned `session_factory`
would not honor that override (it is a plain internal method call, invisible to FastAPI's
dependency-override table), forcing every one of those files to ALSO learn a second,
resolver-specific override mechanism.

**Decision**: `get_current_user` declares `db: AsyncSession = Depends(get_db)` directly, and
`ProgramRosterResolver.resolve(email, db)` takes the session as a per-call argument — the resolver
itself holds only the cache dict + `asyncio.Lock` (no DB handle of its own). This makes the
existing `app.dependency_overrides[get_db]` convention (already used by 4+ test files) transparently
correct for the new roster query too, with zero extra wiring in those files. Reversible: swapping to
a resolver-owned `session_factory` later touches one call site inside `program_roster_resolver.py`.

### D-02: Dev-bypass drops the `groups` claim entirely rather than leaving it empty · blast:feature · rev:mechanical · adr:—

**Context**: AC-6 requires deleting `dev_bypass.py:98`'s synthetic `groups = [f"{prefix}{program}"
...]` construction. With `programs` now traveling as its own top-level claim (AC-4), `groups` on a
dev-bypass token would serve no further purpose — the only two things it ever fed were `programs`
(via `_parse_programs`, deleted) and `CurrentUser.groups`'s raw pass-through, which dev-bypass
tokens have never populated meaningfully (a synthesized `["program-alpha"]` list decoded from the
one JWT dev-bypass itself just encoded, not a real Keycloak-issued value).

**Decision**: the dev-bypass claims payload omits `groups` entirely (no key), rather than setting
`"groups": []` explicitly. `CurrentUser.groups`'s general mapping in `get_current_user`
(`claims.get("groups")` → `[]` if absent) is unchanged and handles the omission identically to
today's "absent groups claim" case (AUTH-01-TC-20) — no new branch needed.

### D-03: Cold cache-miss (`db_query` tier) performance budget set to p95 < 100ms, mirroring `PersonaResolver`'s own Tier-3 budget · blast:feature · rev:mechanical · adr:—

**Context**: Research Condition 1 requires a PLAN-phase prototype measurement proving the roster
query fits inside AUTH-04's existing p95 < 300ms end-to-end `GET /api/programs` budget, but no
story-specific number is given beyond that end-to-end ceiling. Critically, AUTH-04's OWN perf test
(`tests/perf/test_programs_perf.py`) cannot validate this by itself: it mints tokens exclusively via
`POST /auth/dev-bypass`, which (per FR-3) always takes the `kid == DEV_BYPASS_KID` branch and skips
the roster query entirely — so the existing 300ms measurement structurally never exercises the new
roster-DB round trip at all, and never will, however long dev-bypass tokens are used for it.

**Decision**: a dedicated `tests/perf/test_program_roster_resolver_perf.py` measures
`ProgramRosterResolver.resolve()`'s cold (`db_query`-tier) latency directly against a live migrated
test database, asserting p95 < 100ms — the same budget `PersonaResolver`'s own cold Tier-3 test
(`test_persona_resolver_perf.py`, `COLD_P95_BUDGET_MS = 100.0`) uses for a structurally comparable
single-table, indexed, single-predicate lookup. 100ms leaves ample headroom inside the 300ms
end-to-end ceiling alongside `/api/programs`'s already-measured persona-resolution + query +
serialization cost. If the real measurement (task T-17) breaches 100ms, that is reported as a
finding with the measured number, not silently loosened.

### D-04: Test-file scope widens beyond the 3 files REQUIREMENTS.md names, to include every file that breaks as a structural consequence of `get_current_user`'s new dependency signature · blast:feature · rev:mechanical · adr:—

**Context**: REQUIREMENTS.md's Condition 2 mitigation and Scope § In name exactly 3 test files for
refactor (`test_auth_groups.py`, `test_auth_dev_bypass.py`, `test_auth_config.py`). Auditing every
test file that constructs its OWN throwaway `FastAPI` app (setting `app.state.jwks_cache` directly,
never `app.main.create_app`) shows two more — `test_auth_jwt_validation.py` and
`test_ingest_token_isolation.py` — that wire `Depends(get_current_user)` without setting
`app.state.program_roster_resolver`; since FastAPI resolves every declared dependency parameter
eagerly regardless of which code branch inside the function body actually uses it, both would raise
`AttributeError` on `request.app.state.program_roster_resolver` for EVERY request, even one that
never queries the roster. Separately, `test_auth_jwt_validation.py` also carries a `params ==
{"credentials", "settings", "jwks_cache"}` regression test asserting `get_current_user`'s exact
signature has no DB dependency — a real, foreseeable collision with AC-1's own requirement that
session construction query `program_roster`, not a hypothetical. Finally, `test_programs.py`
(`GET /api/programs`'s own 1077-line test suite) builds ~9 tokens via `groups=[...]` expecting the
now-retired groups→programs derivation to scope its non-cio assertions — AC-8's "zero code change"
promise for `app/api/programs.py` does not extend to that file's OWN fixture-construction code,
which must track whatever actually produces `session.programs` now.

**Correction (AF-09, accepted at human-review 2026-09-09)**: the Context above, and the F-14/T-15
notes in `tasks.json`, both counted `test_programs.py`'s TC-10 among the "PII-payload-only" tests that
"never read the parsed programs value" and therefore needed no change. That was wrong. TC-10 asserts
`returned_count == 1`, a value the non-cio `WHERE program_id IN current_user.programs` clause produces,
so it failed `0 != 1` at T-15's baseline and needed a `program_roster` seed like the rest. Its `groups`
claim was deliberately retained, because in that test the claim's job is to be PII bait, not to scope.
T-15 also found TC-05 green-for-the-wrong-reason (AF-10). Both are fixed in the shipped code; this note
corrects the decision record so D-04's file-by-file reasoning is not trusted verbatim by a later reader.

**Decision**: scope the test-refactor work explicitly to 7 files — the 3 REQUIREMENTS.md names plus
`test_auth_jwt_validation.py`, `test_ingest_token_isolation.py`, `test_programs.py`, and a
comment-only fix in `test_programs_perf.py` (its module docstring cites the retired
`PROGRAM_GROUP_PREFIX` mechanism) — each as its own tracked task (T-09/T-10, T-11, T-12, T-13, T-14,
T-15, T-16) rather than discovering the remainder mid-implementation. The narrowest fix per file: a
stub `ProgramRosterResolver` for files that don't test roster derivation itself
(`test_auth_jwt_validation.py`, `test_ingest_token_isolation.py`), and real `program_roster` seeding
only where the test's own purpose requires it (`test_auth_groups.py`, `test_auth_dev_bypass.py`,
`test_programs.py`).
