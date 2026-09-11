# Agent flags — AUTH-07

Raised by implementation workers during `/arh-implement`. Triage with `/arh-human-review AUTH-07`.

### AF-01: `_HERMETIC_SETTINGS_DEFAULTS` did not pin the two new Settings fields — FIXED

- **status**: resolved
- **kind**: risky-pattern
- **raised-by**: T-01
- **source**: `services/api/tests/conftest.py:753` (`_HERMETIC_SETTINGS_DEFAULTS`)

`_HERMETIC_SETTINGS_DEFAULTS` pins every existing `Settings` field (OIDC / CORS / environment) to a
literal so `build_app()`-based tests never silently inherit a real environment value. The dict's own
comment recounts the 2026-09-08 `oidc_redirect_uri` incident that this exact gap caused.

T-01 added `frontend_login_url` and `persona_precedence_order` but did **not** add them there —
`conftest.py` is outside T-01's file scope (`.claude/rules/surgical-changes.md`), so the worker
flagged it rather than fixing it inline.

**Consequence if untriaged**: T-08's `test_auth_logout.py` uses `build_app()` for `GET /auth/logout`.
Its "`frontend_login_url` unset → 501" cases would pass or fail based on the developer's shell
environment or a local `services/api/.env`, rather than deterministically. T-08 should pin
`frontend_login_url` explicitly, following the same precedent.

### AF-02: revision-isolation tests anchored to "head" break on every new migration — FIXED

- **status**: resolved
- **kind**: risky-pattern
- **raised-by**: T-02
- **source**: `services/api/tests/test_migrations.py:536` (`TestRollupQueryIndexRevision.test_index_present_at_004_and_absent_at_003`)

The test hardcoded the assumption that head is `004_rollup_query_indexes` — true only while 004 was
the newest revision. Adding `005_persona_precedence` made it head and broke the test immediately.

T-02 fixed it at root cause, in a file already inside its own scope, by anchoring the test to an
explicit `downgrade(REVISION_004)` rather than trusting `migrated_db`'s initial upgrade-to-head to
land on 004.

**Consequence if untriaged**: the fix is correct but local. The next migration appended after 005
will hit the same class of break unless future revision-isolation tests anchor to their own named
revision instead of "head". Worth deciding whether that becomes a documented convention in
`.claude/skills/alembic-patterns/SKILL.md`.

### AF-03: `test_rollup_rebuild_perf` is load-sensitive — RESOLVED, not a regression

- **status**: resolved-no-action
- **kind**: flaky-test
- **raised-by**: T-03
- **source**: `services/api/tests/perf/test_rollup_rebuild_perf.py:216` (`test_org_rebuild_budget_and_growth_curve`)

T-03's full-suite run reported this failing at a measured 8.1x against an 8.0x growth-ratio ceiling.
It is a BED-05 perf test that T-03 never touched.

**Verified, not assumed.** Three data points settle it:

1. The clean pre-change baseline (before any AUTH-07 code landed) ran `pytest -q` to **514 passed,
   0 failed** — this test passed.
2. T-03's failing run happened while **three implementation workers were executing test suites
   concurrently** on the same machine.
3. Re-run in isolation immediately afterward: **3 passed in 67s**.

So the failure was contention-induced, not caused by any AUTH-07 change. No code action needed.

**Standing consequence**: this test cannot be trusted under concurrent load. Later `/arh-implement`
rounds must not run the full suite from inside a parallel worker — scope worker test runs to their
own files and leave whole-suite runs to the serial evidence pass. Workers dispatched after T-03 were
given exactly that instruction.

### AF-04: `resolve_precedence()` bypassed the 300s cache — AC-7 conflict, now FIXED

- **status**: resolved (gate round 2)
- **kind**: risky-pattern / possible-ac-violation
- **raised-by**: T-05
- **source**: `services/api/app/core/persona_resolver.py::resolve_precedence`

**Verified, not assumed**: `resolve_precedence()` contains zero references to `self._cache`
(`resolve()` retains six). Every call performs fresh Tier-1/2/3 lookups via `_lookup_tiers`.

Per **D-06**, `get_current_user` calls `resolve_precedence` to select `CurrentUser.role`, so this
runs on **every authenticated request** — and `rbac-checks`/`/api/me` then call `resolve(role)`
immediately afterward, repeating the same tier walk. For a Tier-3-only role that is **two Postgres
queries per request** where the design intends one.

**Why this may violate AC-7**, quoted verbatim from `docs/stories/AUTH-07.md`:

> Given `GET /api/me` is called repeatedly for the same session while `persona-resolver`'s 300s cache
> is warm, then **no additional Tier-1/2/3 lookup runs** — this route owns no cache of its own, it
> only calls the existing resolver.

Repeated `/api/me` calls will run additional tier lookups through the uncached `resolve_precedence`
path even with `resolve()`'s cache fully warm. On a literal reading, that is AC-7 unmet.

**Counter-argument on record** (T-05's own): this follows D-06 literally — the method was built as a
refactor of the non-caching `_resolve_uncached`, not of `resolve()`'s cache layer — so it is
compliant with the logged decision, and DECISIONS.md never discusses the double-query cost. In the
common case Tier-1/Tier-2 resolve from in-memory dicts, so the practical cost is only real for
Tier-3-resolved roles.

**Why it was not fixed inline**: T-06 owns `app/core/auth.py`, not `persona_resolver.py`. No task in
the DAG has both the scope and the mandate to change this. Fixing it means either caching inside
`resolve_precedence` or having it seed `self._cache` for the winning role.

**Disposition**: referred to the Validate ∥ Review gate. If review rules AC-7 unmet, this becomes a
`CRITICAL`/`HIGH` finding and the fix loop addresses it at root cause; if review accepts D-06's
literal reading, it ships as a documented carry-forward with the NFR-performance owner's sign-off.

### AF-05: three test files outside the file plan needed repair — FIXED

- **status**: resolved
- **kind**: scope-expansion (necessary)
- **raised-by**: T-06 (diagnosed), orchestrator (fixed)

T-06's new `Depends(get_persona_resolver)` on `get_current_user` (D-06) and T-08's new `/auth/logout`
route broke **4 tests in 3 files that PLAN.md's `file_plan` does not list**:

| File | Failure | Cause |
|---|---|---|
| `tests/unit/test_auth_groups.py` (×2) | `AttributeError: 'State' object has no attribute 'persona_resolver'` | T-06 |
| `tests/unit/test_ingest_token_isolation.py` (×1) | same | T-06 |
| `tests/unit/test_auth_accessibility_scope.py` (×1) | `/auth/logout` absent from an exact expected-route-set assertion | T-08 |

The first two hand-roll their own FastAPI app instead of `create_app()`/`build_app` (each documents
why in its own docstring), so neither set the new `app.state` attribute. FastAPI resolves every
declared dependency eagerly regardless of which branch runs, so the attribute must exist even though
these tests never reach the code path that uses it.

**These are not unrelated carry-forward** — AUTH-07's own changes broke them, so
`.claude/rules/surgical-changes.md` requires fixing them rather than deferring. Each worker correctly
flagged instead of fixing, because the files sat outside its assigned scope.

**Fix applied**, following the codebase's own precedent rather than inventing one:

- Added a `_StubPersonaResolver` to each of the two files, mirroring the existing
  `tests/perf/test_programs_perf.py::_StubPersonaResolver` — the same precedent
  `_StubProgramRosterResolver` already documents itself as following. Both stub methods raise
  `AssertionError`, because they are provably unreachable from these files: `get_current_user` only
  calls `resolve_precedence` for 2+ surviving roles, and every token here is minted through
  `build_access_token`'s `role=` parameter, which writes `realm_access.roles` as a **single-element**
  list. Verified: neither file uses `extra_claims` to inject multiple roles.
- Added `"/auth/logout"` to the accessibility test's expected route set. Its substantive assertion
  (no `/auth/*` route declares an HTML response class) now covers the new route too and passes —
  `/auth/logout` mirrors `/auth/login`'s decorator exactly, declaring no `response_class`, so it
  resolves to FastAPI's `JSONResponse` default despite returning a `RedirectResponse`.

**Verified**: 13 passed across the three files; `ruff` clean; `mypy` clean over 123 source files.

**Note for PLAN.md accuracy**: the feature's true file footprint is 3 files wider than `file_plan`
records. Worth reflecting if the plan is ever regenerated.

### AF-06 [CONFIRMED N/A]: runtime render_check unavailable for `web` stack — no browser/E2E tooling

- **status**: triaged — confirmed N/A (2026-09-11), no code action
- **kind**: evidence-na
- **raised-by**: evidence-pass (session-end)
- **source**: `docs/config/project-commands.yaml` (`test_e2e: ""`)

The `web` stack's runtime boot check (`/health`-equivalent `/` root probe, 307, clean boot log) is
boot-only evidence per the skill: a client-rendered app can serve 200/307 with an empty or partially
mounted tree. `test_e2e` is blank (`project-commands.yaml:8` — "not yet configured — no e2e framework
(Playwright/Cypress) declared in ADR-0001") and no such package is installed (`apps/web/package.json`).

**Verified, not assumed**: manually curled the boot chain end-to-end — `GET /` → 307 `/overview` → 307
`/login` → 307 to the real Keycloak authorize endpoint → 200 real Keycloak-rendered login HTML. This
proves the SSR redirect chain executes correctly, but is not a substitute for an automated
render-mount assertion.

**Disposition**: `runtime` dimension is still `PASS` (boot verdict unaffected) with `render_check:
"unavailable"` recorded on the `web` stack entry, per skill. `/arh-human-review` should eyeball the
running app once, or the team should wire Playwright/pa11y before the next evidence pass raises this
again.

### AF-07 [CONFIRMED N/A]: `design_check` dimension N/A — no tool wired, and AUTH-07 itself is `design: n/a`

- **status**: triaged — confirmed N/A (2026-09-11), no code action
- **kind**: evidence-na
- **raised-by**: evidence-pass (session-end)
- **source**: `docs/config/project-commands.yaml` (`design_check: ""`)

`design_check:` is empty — no axe/pa11y tool has been chosen or installed yet (`docs/design/schema.json`
`fileKey`/`url` still TODO). Independently, AUTH-07 carries `design: "n/a"` in
`docs/features/AUTH-07/state.json`: no `AUTH` epic exists in `docs/design/schema.json`, and AC-15
requires `GET /logout` to have zero UI surface (direct-URL-only route, no mockup or component touched).
Both facts point the same direction — nothing to design-check this session, and no tool to run it with
regardless.

**Disposition**: `design_check` dimension recorded `N/A`. `/arh-human-review` triages this flag before
commit; `accept` confirms N/A is legitimate (true here on two independent grounds), `reject` would mean
wiring a design-check tool first.

**RESOLUTION (gate round 2).** Both gate agents independently ruled AC-7 **unmet** in round 1 —
`code-review-agent` graded it **F-1 HIGH → BLOCKED**, `validation-agent` returned **PARTIAL**. The
decisive evidence was that `docs/features/AUTH-07/DATA-DESIGN.md` § 8 already promised the Tier-3
lookup "is cached at 300s per role ... not re-queried per candidate role on every request" — so the
shipped code contradicted the feature's own design document, making this a genuine defect rather
than a defensible reading of D-06. A test, `test_resolve_precedence_bounded_tier3_queries_live_db`,
had also locked the un-cached behaviour into the suite.

Fixed at root cause: a new `PersonaResolver._cached_lookup(role)` extracts the double-checked-locking
cache-then-tier-lookup that previously lived inline in `resolve()`, and `resolve_precedence` now calls
it per candidate instead of `_lookup_tiers` directly. It reuses the **same** `self._cache`,
`self._lock`, `_CACHE_TTL_SECONDS`, and `role.casefold()` key — no second cache, lock, or TTL. A miss
is still never cached (AC-26). `resolve()` was deliberately left untouched, because
`tests/perf/test_persona_resolver_perf.py` monkeypatches `_resolve_uncached` to prove the warm path
never calls it; review traced both call sites (`app/api/me.py:67`, `app/core/rbac.py:285`) and
confirmed no functional divergence between the two entry points.

The superseded test's premise was corrected and a new one added —
`test_resolve_precedence_repeated_call_reuses_warm_cache_auth07_ac07` — which counts real `SELECT`s
through a SQLAlchemy engine hook against live Postgres across two calls and asserts the second adds
**zero**. That is AC-7's literal repeated-call guarantee, and it was the coverage both agents named
as missing. Round 2: validation **PASS** (AC-7 MET), review **PASS** (F-1 resolved at root cause).
`DATA-DESIGN.md` § 8 is now literally true and was correctly left unedited.


---

## Triage dispositions (2026-09-11, at the user's direction: "fix them then commit")

**AF-01 — FIXED.** Added `frontend_login_url: None` and `persona_precedence_order: None` to
`services/api/tests/conftest.py::_HERMETIC_SETTINGS_DEFAULTS`, with a comment tying the change to the
2026-09-08 `oidc_redirect_uri` incident the surrounding block already documents. `build_app()` tests
can no longer inherit either value from a developer's shell or a stray `services/api/.env`. The
"unset -> 501" branch of `GET /auth/logout`'s completeness gate and the all-tiers-unset
`_DEFAULT_PERSONA_PRECEDENCE` branch are now the deterministic ones under test. T-08's per-test
overrides still take precedence and still pass (76 tests green across
`test_auth_logout.py`/`test_auth_config.py`/`test_auth_oidc_login.py`).

**AF-02 — FIXED.** T-02 had already repaired the one broken test by anchoring it to an explicit
`downgrade(REVISION_004)`; what remained was the recurrence risk. Recorded the rule in
`.claude/skills/alembic-patterns/SKILL.md` § Anti-patterns, citing this exact instance, so the next
migration's author is warned before appending a revision rather than after.

**AF-06 — CONFIRMED N/A, no code action.** The `web` stack's runtime `render_check` needs a browser
driver. ADR-0001 declares no E2E framework and `test_e2e` is empty in
`docs/config/project-commands.yaml`; installing Playwright or pa11y is a tooling decision requiring
its own ADR, not something to fold into this feature. The `evidence-na` flag exists to have a human
confirm the N/A, and that is done: boot health was instead verified directly during the evidence
pass, which exercised the full SSR redirect chain live (`/` -> `/overview` -> `/login` -> real
Keycloak IdP, 200). The evidence verdict does not depend on this dimension.

**AF-07 — CONFIRMED N/A, no code action.** Two independent grounds, either sufficient. First,
`design_check` is empty in `docs/config/project-commands.yaml` and its own comment states this is
deliberate — "left blank on purpose ... `/arh-implement` will raise an evidence-na AF-NN for
design_check until a tool is chosen and wired here". Second, AUTH-07 is `design: n/a`:
`docs/design/schema.json` has no `AUTH` epic and AC-15 forbids any rendered UI, so there is no
surface for a design check to inspect. Confirmed; wiring a tool is out of scope for this story.

**Review's non-blocking findings** (F-2 contract-drift, now largely moot; F-3 `activity.jsonl`
mutation, pre-existing and unrelated; F-5 `migrated_db` fixture race under partial selection; F-6
stale AF-04 text, corrected above) carry forward to the PR body per
`.claude/rules/surgical-changes.md`, which directs recording rather than inline-fixing unrelated
issues.
