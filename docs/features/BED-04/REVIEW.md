# Code Review — feature/BED-04 (round 2)

- Date: 2026-09-03
- Mode: story (GATE MODE — report-only, `/arh-implement` Validate ∥ Review)
- Files reviewed: 12 (3 source/test, 4 docs, 5 feature artefacts)
- Verdict: PASS

Round 1's verdict is void (source changed). This report supersedes it. Round 1's
citation of `DATA-DESIGN.md § 8` as carrying the "inherits the session factory's
timeout" claim was wrong — only `REQUIREMENTS.md:46` carried it; that line is now
corrected.

## Executive summary

🟢 **F-1 (HIGH, round 1) is CLOSED.** The `system_metadata` read is now genuinely
bounded: `wait_for(_query(), timeout=_QUERY_TIMEOUT_SECONDS)` at
`freshness.py:155` wraps the *entire* session lifecycle — pool checkout,
`__aenter__`, `execute`, `scalar_one_or_none`, `__aexit__` — not just the SELECT,
so pool exhaustion is bounded too. The construct is character-for-character the
`persona_resolver._resolve_tier3` precedent (`persona_resolver.py:186-197`): same
`from asyncio import Lock, wait_for`, same nested `_query()`, same
`except TimeoutError` (correct on this repo's `requires-python = ">=3.11"`, where
`asyncio.TimeoutError` is an alias of builtin `TimeoutError` — on 3.10 it would
not have caught). The timeout raise sits inside `async with self._lock`, so
`Lock.__aexit__` releases on the exception path; the regression test proves this
empirically by re-querying successfully afterwards. D-04 records the decision, and
all five doc surfaces (`REQUIREMENTS.md:46`, `DATA-DESIGN.md:47`,
`docs/requirements/api.md#freshness-api`, `services/api/README.md`, module
docstring) agree with the code. No blockers, no HIGH, no MEDIUM. Seven LOWs, all
cosmetic or carry-forward.

## Findings summary

| Severity | Count | Category distribution                                                        |
|----------|-------|------------------------------------------------------------------------------|
| CRITICAL |   0   | —                                                                            |
| HIGH     |   0   | —                                                                            |
| MEDIUM   |   0   | —                                                                            |
| LOW      |   7   | integration (2), design-patterns (1), scope-creep (2), module-structure (2)   |

## Answers to the gate's specific questions

**1 — Is the read bounded, and is `wait_for` placed correctly?** Yes.
`freshness.py:143-161`: warm fast path (no lock) → `async with self._lock` →
double-check → `wait_for` around the nested `_query()`. The bound covers the real
I/O because the whole `async with self._session_factory()` block lives inside
`_query()`. The lock is acquired *outside* the bound, which is the correct order:
it means the 3.0s ceiling applies to the critical section, so the worst case for a
queued concurrent caller is now `3.0s + ε` instead of unbounded. On `TimeoutError`
the raise exits the `async with self._lock` block and the lock is released by
`__aexit__`.

**2 — Does the timeout preserve D-03's no-negative-caching invariant?** Yes, under
every interleaving. `self._cached_value` / `self._expiry` are written only at
`freshness.py:170-171`, reachable only after both the `TimeoutError` handler and
the `row is None` guard have been passed; there is no `finally`, no partial write,
and the writes happen while the lock is held. Even the fast-path reader is safe:
the two assignments have no `await` between them, so no other coroutine on the
single-threaded loop can observe `_cached_value` set with `_expiry` still `0.0`.

**3 — Is the row-absent path still exactly one warning?** Yes, and the two warning
paths are strictly mutually exclusive. If `wait_for` raises, control leaves the
function before the `row is None` check (`:161`); if it returns, no timeout
warning is possible. TC-02's `len(records) == 1` assertion cannot be broken by the
refactor. The only theoretical interaction is a live-DB read in TC-01/TC-02
exceeding 3.0s — that would surface as an obvious failure on the
`detail == _NOT_RUN_MESSAGE` assertion, not as a silent second record. Not raised
as a finding: no measurement supports calling it a real flake risk
(`performance-baseline.md` — "don't optimise without a measurement" cuts both
ways), and `migrated_db` has already warmed the connection.

**4 — Barrel hygiene.** Correct. `app/services/__init__.py` imports and re-exports
only `FreshnessAccessor`; `_QUERY_TIMEOUT_MESSAGE`, `_QUERY_TIMEOUT_SECONDS`,
`_NOT_RUN_MESSAGE` and `_CACHE_TTL_SECONDS` all stay module-private, matching
`guardrail_compute.PASSING_STATUS`'s precedent and
`reusability-baseline.md` ("implementation details stay private"). The test
imports `_QUERY_TIMEOUT_MESSAGE` from `app.services.freshness` directly, never
from the barrel and never as a re-typed literal. See F-3 for the docstring nit.

**5 — Is D-04 adequate?** Yes. It states the context (F-1, plus the verified fact
that `app/core/db.py:17`'s `create_async_engine(settings.database_url)` sets no
`connect_args` / `command_timeout` / statement timeout, so there was no timeout to
inherit), justifies 3.0s by reference to `_TIER3_TIMEOUT_SECONDS` rather than
inventing a number, justifies 500-over-503 by the same
consistency-with-`app/core/errors.py` argument BED-04-FR-1 already gives the
row-absent path, justifies the distinct message constant, restates the
no-negative-caching invariant as shared with D-03, and records `app/core/db.py` as
deliberately out of scope with the blast-radius reason. Header slugs
(`blast:feature · rev:mechanical · adr:—`) are present and correctly scoped — a
3.0s local bound in one accessor does not warrant an ADR. It reads as a peer of
D-01..D-03, not a bolt-on.

**6 — Contract drift.** Additive, not breaking. `docs/requirements/api.md#freshness-api`
gains a `timeout:` key in the same diff as the code, so the contract is not stale.
The addition cannot break a consumer: all five `consumed_by` stories (OVW-01,
ARC-01, DEV-01, PMD-01, EMD-01) are at `phase: story-validated` with zero
implementation — `grep` finds no reference to `FreshnessAccessor` or
`get_last_successful_run` outside `freshness.py`, its two tests, and the barrel.
The new failure mode reuses the *existing* status code (500) and the existing
`StarletteHTTPException` envelope; only `detail` differs. A consumer that
string-matches `detail == "ingestion job may not have run yet"` to render a
"never ingested" state already needed an else-branch for generic 500s, and now
has a documented second string to match instead of an undocumented hang.

**7 — Is the regression test real?** Real, not vacuous. `_QUERY_TIMEOUT_SECONDS` is
read as a module global at call time inside the method body, so
`monkeypatch.setattr(freshness, "_QUERY_TIMEOUT_SECONDS", 0.01)` genuinely lowers
the live bound (it is not a default argument captured at def time — which would
have made the patch inert and the test vacuous). `_FakeSessionCtx.execute` awaits
`asyncio.sleep(0.05)`, a real suspension 5× the patched bound, so the timeout
fires deterministically rather than racing. `FakeSessionFactory.__call__` reads
`self.delay_seconds` per call, so the `factory.delay_seconds = 0.0` mutation
before the re-query is effective. The test asserts the status code, the exact
imported `_QUERY_TIMEOUT_MESSAGE` constant, exactly one WARNING record, the
allowlisted `JSONFormatter` key set (no PII), and `call_count == 2` — which is the
D-03/D-04 no-negative-caching proof. Delete the `wait_for` and the test fails at
`pytest.raises(HTTPException)`.

## Detailed findings

### LOW

#### F-1 — integration: logged `reason` hardcodes `3.0s` independently of the constant
- Category: integration points
- Path: `services/api/app/services/freshness.py:159`
- Source: DECISIONS.md D-04 (`_QUERY_TIMEOUT_SECONDS` is the single source of the bound); `.claude/rules/pattern-consistency.md`
- Description: `extra={"reason": "system_metadata query exceeded 3.0s timeout"}` restates the bound as a literal. If `_QUERY_TIMEOUT_SECONDS` ever changes, the operator-facing log silently lies. The regression test asserts only the key set, so it would not catch the drift. Kept LOW because `persona_resolver.py:197` does exactly the same thing ("Tier-3 query timeout after 3.0s") — this is precedent-consistent, not novel.
- Suggested fix: `f"system_metadata query exceeded {_QUERY_TIMEOUT_SECONDS}s timeout"`. Optional; changing it here without changing the precedent trades one inconsistency for another.

#### F-2 — module structure: PLAN.md not updated for D-04
- Category: module structure & boundaries
- Path: `docs/features/BED-04/PLAN.md:7` and `:11-41`
- Source: DECISIONS.md D-04
- Description: §1 still reads "Three entries … D-01 … D-03"; there are now four. §2's module hierarchy still lists `_NOT_RUN_MESSAGE` as the module's only constant and does not mention `_QUERY_TIMEOUT_SECONDS` / `_QUERY_TIMEOUT_MESSAGE`. PLAN.md is the human narrative a reviewer or downstream story reads first, so the undercount is misleading.
- Suggested fix: change "Three entries" to "Four entries", add D-04 to the enumeration, and add the two constants to §2's `public:` block.

#### F-3 — design patterns: docstrings enumerate only `_NOT_RUN_MESSAGE`
- Category: design patterns
- Path: `services/api/app/services/__init__.py:13` and `services/api/tests/unit/test_freshness.py:24-27`
- Source: `.claude/rules/reusability-baseline.md` (the rule the barrel docstring is citing)
- Description: the barrel docstring's "stays module-private for the same reason" example names only `freshness._NOT_RUN_MESSAGE`; the test docstring's "imported, never re-typed" paragraph likewise names only `_NOT_RUN_MESSAGE`, while line 48 now imports both constants. The behaviour is correct in both files — only the prose is one constant behind.
- Suggested fix: say `freshness._NOT_RUN_MESSAGE` / `_QUERY_TIMEOUT_MESSAGE` in both places.

#### F-4 — module structure: REQUIREMENTS.md Observability NFR lists only one warning path
- Category: module structure & boundaries
- Path: `docs/features/BED-04/REQUIREMENTS.md` § Non-functional requirements → Observability
- Source: DECISIONS.md D-04 (mandates a second `logger.warning()`)
- Description: the Observability bullet still reads "`logger.warning()` on the row-absent path per BED-04-FR-1" and does not mention the timeout warning, even though the Performance bullet on line 46 was correctly updated for D-04. An operator reading only the NFR section would not know a second WARNING exists.
- Suggested fix: add the timeout warning to the Observability bullet, citing D-04.

#### F-5 — integration: `wait_for` cancels a mid-statement pooled connection (repo-wide)
- Category: integration points
- Path: `services/api/app/services/freshness.py:147-161`
- Source: `.claude/rules/pattern-consistency.md`; precedent `app/core/persona_resolver.py:186-197`
- Description: on timeout, `wait_for` cancels `_query()` while `session.execute()` is in flight; the `async with` unwinds through `AsyncSession.__aexit__` → `close()` during the `CancelledError`, with the driver connection interrupted mid-statement. SQLAlchemy's pool invalidates a connection whose reset fails, so blast radius is one discarded connection — not a leak — but the reset path is exercised on a cancelled task. Explicitly LOW and **not** raised as a defect against BED-04: the identical construct is the merged AUTH-02 precedent, and `pattern-consistency.md` says a new file follows the dominant pattern over an abstractly safer one. Fixing it here alone would make the codebase less consistent, not more.
- Suggested fix: none in this PR. Carry-forward — address once, repo-wide, alongside the engine-level timeout story that D-04 defers.

#### F-6 — scope-creep: `docs/requirements/api.md` edited but absent from `tasks.json` `file_plan`
- Category: scope-creep
- Path: `docs/requirements/api.md` § `freshness-api`
- Source: `docs/features/BED-04/tasks.json` `file_plan` (F-01..F-05 only)
- Description: the shared-contract update is not in any task's declared `files[]`. **Do not revert it** — `review-assessment`'s `contract-drift` rule requires a story to update the contract it `produced_by` in the same diff, so the edit is mandated remediation and its absence would itself be a HIGH finding. The defect is in the plan, not the diff: `file_plan` should have carried an `F-06` for the produced contract.
- Suggested fix: add `F-06 → docs/requirements/api.md` to `tasks.json` `file_plan` and attach it to the barrel/documentation task, so the scope baseline matches what the contract rule compels.

#### F-7 — scope-creep: untracked, un-gitignored directories sit in the review tree
- Category: scope-creep
- Path: `dashboards/` (6 HTML files), `.claude/worktrees/`, `.claude/agent-memory/`, `services/api/.claude/`
- Source: `.claude/rules/surgical-changes.md` ("every changed line must trace to the task")
- Description: `git check-ignore` reports all four as NOT-IGNORED. None traces to a BED-04 task and none is on the orchestrator's excused list (which covers only `apps/web/pnpm-workspace.yaml`). A `git add -A` / `git commit -a` for BED-04 would sweep them in — `.claude/worktrees/` in particular contains full working copies, and `dashboards/` duplicates content that belongs under `docs/design/mockups/`. Not a code defect; a commit-hygiene hazard at the exact moment this branch is about to be committed.
- Suggested fix: stage BED-04's files explicitly by path, never `-A`. Separately, add `.claude/worktrees/` and the agent-memory paths to `.gitignore` and decide where `dashboards/` belongs — carry-forward, out of BED-04 scope.

## Dimension verdicts

| Dimension | Verdict |
|---|---|
| Module structure & boundaries | Clean. One new module in an existing package; `freshness.py` imports only `app.core.db` + `app.models.ingestion`, no reverse dependency, no route. F-2/F-4 are prose-only. |
| Design patterns | Follows the research Pattern Map exactly — `PersonaResolver`'s cache shape *and now its timeout shape*, symbol for symbol. No invented shape. |
| Component / module architecture | `session_factory` keyword-only injection seam unchanged; the nested `_query()` closure is the precedent's own composition, not a new abstraction. |
| Integration points | The gap that made round 1 a HIGH is closed; error envelope unchanged (500 via the registered `StarletteHTTPException` handler); no retry, correctly — D-04 bounds instead of retrying. |
| Testability | Strong. The timeout branch is reachable and deterministically exercised without a 3s wait; `FakeSessionFactory.call_count` proves I/O counts rather than trusting return values. |
| Safety & security | Read-only, two non-PII columns, parameterised `select()` (no string SQL), both warnings PII-free with an assertion pinning the exact key set. `detail` strings leak no internal state. |
| scope-creep | Two LOWs (F-6 plan gap, F-7 tree hygiene). Source diff itself is exactly F-01..F-05. |
| adr-violation | None. D-01/D-02/D-03 all honored; D-04 is the record *for* this change, and `app/core/db.py` is untouched as D-04 states. |
| contract-drift | None — additive, updated in the same diff, zero live consumers. |
| rule-violation | None. `performance-baseline.md`'s explicit-timeout clause is now satisfied; TTL + invalidating event still documented; no pagination concern (singleton row). |
| pattern-violation | N/A — the four stack `*-patterns` skills are unfilled scaffolds (G15); PLAN.md §1 binds to in-repo precedents instead, and the diff honors them. |

## What went well

- The fix reuses the repo's own precedent instead of inventing a timeout mechanism — same import line, same nested-`_query()` shape, same exception class as `persona_resolver._resolve_tier3`.
- The bound was placed to cover pool checkout and session teardown, not just `execute()` — strictly stronger than a statement-level timeout would have been.
- `_QUERY_TIMEOUT_MESSAGE` was kept distinct from `_NOT_RUN_MESSAGE` and both kept off the barrel; the test imports the constants rather than re-typing the strings, so a future rename fails loudly.
- Round 1's false REQUIREMENTS.md claim was corrected rather than quietly worked around, and D-04 names the false claim in its Context.
- The engine-wide timeout was considered, rejected with a stated blast radius, and recorded in D-04 — the right call for a story-scoped fix.

## Recommendation

**PASS.** F-1 is closed on the merits. Nothing here blocks. The seven LOWs are
prose/hygiene items: F-2, F-3 and F-4 are one-line artefact edits worth doing
before the PR since they are internal-consistency drift introduced by this very
round; F-1 and F-5 are precedent-consistent and better fixed repo-wide than
locally; F-6 and F-7 are carry-forward. Next: `/arh-security-review`.
