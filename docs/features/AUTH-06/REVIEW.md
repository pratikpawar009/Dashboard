# Code Review — feature/AUTH-06 (working tree vs `main`)

- Date: 2026-09-09
- Mode: story (GATE MODE — report-only; no state write)
- Snapshot: round 3 of 3 (hard cap). Porcelain anchor `76b23f011df71feb` unchanged from round 2
  (same two files modified); tracked-diff content digest `100fe31d4bf6c6c3`. Round 1 was
  `307818b3abb61161`.
- Files reviewed: 18 source-scoped + `docs/stories/AUTH-06.md` (harness-owned)
- Verdict: **PASS WITH WARNINGS** — **0 CRITICAL, 0 HIGH, 4 MEDIUM, 8 LOW**

> Finding ids `F-NN` in this report are review findings. They are a **separate sequence** from
> `tasks.json` `file_plan`'s `F-01..F-16` file ids and do not correspond.

## Round-3 delta

Round 2's **F-12** is **CLOSED**. The remedy is both halves of the fix F-12 proposed: `conftest.py`
now derives the pin from the field default, and the login test's comment was rewritten a third time.
Every claim in that comment was measured, not read — see below. One new LOW (**F-14**) falls out of
the remedy. No MEDIUM or LOW re-graded upward; the hermeticity question the orchestrator flagged as a
possible upgrade trigger measured **clean**.

| | Round 1 | Round 2 | Round 3 |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 1 (F-1) | 0 — F-1 closed | 0 |
| MEDIUM | 4 | 4 | 4 (all standing, re-verified) |
| LOW | 6 | 8 | 8 (F-12 closed, F-14 new) |

**Count correction.** Round 2's summary table read `LOW 7`; the enumerated findings were F-6, F-7,
F-8, F-9, F-10, F-11, F-12, F-13 — **8**. Arithmetic slip in the round-2 table, not a re-grade.
Corrected here and carried forward. LOW never gates, so no verdict was affected in either round.

Gates re-run independently on this snapshot, not taken from the hand-off: `uv run ruff check .` →
`All checks passed!` · `uv run mypy .` → `Success: no issues found in 116 source files` ·
`uv run pytest -q` → `497 passed`. All three match the reported values.

### 1. Is the comment accurate? — **Yes. Five claims, five measured true.**

Measured by regressing `app/core/config.py:63` (`oidc_scope`) back to `"openid profile email groups"`
and running the two test files under four pin configurations. Every mutation was restored from a
byte-copy and verified: `config.py` sha256 `678eb1b3…113e` and `test_auth_oidc_login.py` git blob
`c9b9c72e…721d` (the exact post-image in this diff's `index 6b8c42e..c9b9c72` line) both match
pre-experiment, and the full suite re-runs at `497 passed` afterwards.

| # | Claim (comment text) | Measurement | Verdict |
|---|---|---|---|
| 1 | "asserts it on the wire — the scope Keycloak's authorization request actually carries" | the assertion parses `resp.headers["location"]`'s query on the 302, i.e. the authorization-request URL itself | **true** |
| 2 | "a real guard on the shipped default, not just on verbatim forwarding" | scenario A below | **true** |
| 3 | "regress `config.py`'s default and this test fails alongside `test_auth_config.py`" | scenario A: **exactly** `2 failed, 50 passed` — `test_login_redirects_to_keycloak_with_valid_authorization_request` **and** `test_settings_default_field_list_matches_fr1`, no others | **true** |
| 4 | "would stop guarding … the moment someone pins a scope literal in conftest" | scenario B: literal pin restored + default regressed → `1 failed, 51 passed`; only `test_auth_config.py` fails, the login test goes green | **true** |
| 5 | "… or overrides it on this test" | scenario D: `build_app(**_FULL_OIDC_CONFIG, oidc_scope="openid profile email")` + default regressed → `1 failed, 51 passed`; login test green | **true** |

Scenarios, all with `config.py:63` regressed to `"openid profile email groups"`:

| Scenario | Pin configuration | Result |
|---|---|---|
| A | as shipped (derived pin) | `2 failed, 50 passed` — login + config |
| B | literal pin `"openid profile email"` in conftest | `1 failed, 51 passed` — config only |
| D | derived pin + per-test `oidc_scope` override | `1 failed, 51 passed` — config only |

The conftest half is equally accurate. "Constructor kwarg — highest precedence, above env and the
field default" is measured: under `OIDC_SCOPE=ENV-LEAKED-SCOPE` **plus** a `.env` in the CWD carrying
`OIDC_SCOPE=DOTENV-LEAKED-SCOPE`, `Settings(**_HERMETIC_SETTINGS_DEFAULTS).oidc_scope` →
`'openid profile email'`, while the unpinned control `Settings().oidc_scope` → `'ENV-LEAKED-SCOPE'`,
proving the pollution was real and the pin is what blocks it. And
`'program_group_prefix' in Settings.model_fields` → `False`, with
`Settings(program_group_prefix='program-')` raising nothing and setting no attribute — the
`extra="ignore"` swallow the comment describes, confirmed.

This is the third wording and the first that survives measurement. Rounds 1 and 2 both shipped a
false narration of this one assertion (round 1: "`# settings.oidc_scope default`" when it read a
fixture pin; round 2: "proves the shipped default reaches Keycloak" when the pin was still a
literal). What makes round 3 different is not better prose — it is that the *code* changed underneath
it. The derived pin made the round-2 sentence true, which is the right ordering: the fix earned the
claim rather than the claim being trimmed to fit the fix.

### 2. F-12 disposition — **CLOSED.** The remedy introduced no defect.

Both halves landed as proposed. The comment now states what the code does, and the code now does what
the earlier comment wanted to claim.

### 3. Hermeticity — **preserved byte-for-byte. No upgrade.**

The orchestrator's re-grade condition ("if it does not, the fix traded a doc defect for an isolation
regression") does not fire. `Settings.model_fields["oidc_scope"].default` is class metadata: a plain
`str`, read at conftest import time, structurally unreachable by env or `.env` (pydantic-settings'
sources feed *instances*, never `FieldInfo.default`). Derived and literal pins are equal
(`==` and `.encode() ==`), and both produce identical `Settings` under hostile env + hostile `.env`.
pydantic 2.13.4 / pydantic-settings 2.15.0; class-level `model_fields` access raises nothing under
`-W error::DeprecationWarning` (only *instance* access is deprecated).

**Durability of the derived form, measured rather than assumed** — the one way a derived pin could
differ from a literal is if `.default` ever stopped being a value. Both routes there degrade
**loudly, never silently**:

| If `oidc_scope` became… | `.default` | Pinned result under hostile env |
|---|---|---|
| `Field(default_factory=…)` | `PydanticUndefined` | resolves to the factory value; env still blocked (**hermetic**) |
| required (no default) | `PydanticUndefined` | `ValidationError` at every `build_app()` call (**loud**) |

Neither leaks the env value. Recorded so a future reviewer does not have to re-derive it; not a
finding.

### 4. Import-time safety — **no risk.** D-07's rule genuinely does not apply.

`conftest.py:70` already imported from `app.core.config`; widening it to `Settings, settings` adds no
new module import. Measured: importing `app.core.config` from a cold interpreter pulls in exactly
`['app', 'app.core', 'app.core.config']` — no `app.api.*`, no `app.main`, no `app.auth`. D-07's
deferred-import rule exists because `app.main` drags the whole router graph in, and that import is
still deferred at `conftest.py:697`. No circularity: `app.core.config` imports only stdlib, `fastapi`,
`pydantic`, `pydantic_settings`. Its only import-time side effect — constructing the module-level
`settings` singleton — already happened via the pre-existing `settings` import.

One consequence of the widening is filed as **F-14** below.

### 5. Standing findings — 4 MEDIUM and 7 prior LOW re-confirmed as graded

Re-verified by reading the cited code, not by assumption. The round-3 change touched only
`tests/conftest.py` (below line 660) and `tests/unit/test_auth_oidc_login.py`, which no standing
finding cites, so every line number below is unmoved and was spot-checked:

| Id | Sev | Location (re-read this round) | Status |
|---|---|---|---|
| F-2 | MEDIUM | `program_roster_resolver.py:130` — `async with self._lock` still wraps `_resolve_uncached` | Stands |
| F-3 | MEDIUM | `docs/how-to/dev-bypass-auth.md:44-51` — still documents the `groups` round-trip and the deleted `_parse_programs` | Stands |
| F-4 | MEDIUM | `program_roster_resolver.py:152` — `wait_for(..., timeout=_QUERY_TIMEOUT_SECONDS)` | Stands |
| F-5 | MEDIUM | `test_program_roster_resolver_perf.py:204-211` — failure message still names `ix_program_roster_email` | Stands |
| F-6 | LOW | `auth.py:252` (`list(claims.get("programs") or [])`) vs `:228-229` (`isinstance` guard) | Stands |
| F-7 | LOW | `dev_bypass.py:84` — `settings: Settings = Depends(get_settings)`, still unused | Stands |
| F-8 | LOW | `program_roster_resolver.py:192` — `.isoformat() + "Z"` | Stands |
| F-9 | LOW | `program_roster_resolver.py:112-117,138` | Stands |
| F-10 | LOW | `test_program_roster_resolver_perf.py:78,105` — `production_logging`, `_percentile` | Stands |
| F-11 | LOW | working-tree artefacts | Stands — re-measured, see below |
| F-13 | LOW | `file_plan` still 16 entries, diff still 18 files | Stands, **unchanged** |

**F-11 re-measured.** All still true: `docs/activity/activity.jsonl` still `28` insertions / `4`
deletions (not append-only), ING-10's `state.json` + `SECURITY-20260908-1253.md` still uncommitted,
and `.claude/worktrees/` still untracked, still **not** gitignored (`git check-ignore` no match), at
**2.7 GB**.

**F-13 needs no update.** The file set is unchanged from round 2 — 18 source files against a 16-entry
`file_plan`, with `tests/conftest.py` and `tests/unit/test_auth_oidc_login.py` still absent from it.
Round 3 edited those same two files, adding no new ones, so the gap neither widened nor closed. The
round-2 remedy stands verbatim: append them as `file_plan` F-17/F-18 annotated "review-directed
(REVIEW.md F-1/F-12)", or note the exception in the PR body. Orchestrator bookkeeping, not a source
edit.

### F-14 (NEW, LOW) — the module-scope `Settings` import leaves a redundant re-import inside `_build`, under a comment that reads as justifying it

- Category: module structure & boundaries
- Path: `services/api/tests/conftest.py:692` (vs the widened import at `:70`)
- Source: `.claude/rules/surgical-changes.md` — "Remove imports, variables, and functions that YOUR
  changes made unused"
- Description: widening `:70` to `from app.core.config import Settings, settings` made
  `:692`'s `from app.core.config import Settings` inside `_build` redundant — it now shadows the
  module-scope name with the identical object. Nothing detects it: ruff's enabled set (`E,F,I,UP`)
  has no rule for a function-local import shadowing a module-level name, and `F811` does not span
  scopes. Functionally inert. The reason it is worth a line rather than nothing is placement: the
  deferred-import comment at `:694-696` sits *between* `:692` and the `app.main` import at `:697`,
  and opens "Imported inside the closure, not at module scope" before narrowing to `app.main`. A
  reader scanning it attributes the rationale to both imports and concludes `app.core.config` must
  stay deferred — which is false, as the very same patch demonstrates by importing it at module
  scope. Same narration-drift class as F-12, one notch smaller.
- Suggested fix: delete `:692`; the closure resolves `Settings` from module scope. If the local
  import is deliberate, say so in half a line so the deferred-import comment is not read as its
  justification.

## Round-2 delta

Round 1's single HIGH (**F-1**) is **CLOSED**. Two hunks, two files, both confined to the lines F-1
named; nothing else in the tree moved since `307818b3abb61161`. The verdict literal is unchanged
(`PASS WITH WARNINGS`) only because 4 MEDIUMs exceed the `≤3` PASS threshold — the *blocking*
rationale is gone. Nothing here needs a third fix pass.

| | Round 1 | Round 2 |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 1 (F-1) | **0** — F-1 closed |
| MEDIUM | 4 | 4 (all standing, re-verified) |
| LOW | 6 | 7 (6 standing + F-12; F-13 new bookkeeping) |

Gates on this snapshot: `ruff check .` clean · `mypy .` clean (116 files) ·
`pytest tests/unit/test_auth_oidc_login.py tests/unit/test_auth_config.py` → 52 passed ·
full suite 497 passed (per orchestrator, unchanged).

### F-1 closure assessment

**(a) dead kwarg — fully closed.** Verified at runtime, not by reading:
`'program_group_prefix' in Settings.model_fields` → `False`, and
`'program_group_prefix' in _HERMETIC_SETTINGS_DEFAULTS` → `False`. No dead config survives.

**(b) shadowed scope — fully closed, and this was F-1's substance.** The pin now equals the shipped
default (`Settings.model_fields['oidc_scope'].default == 'openid profile email'` ==
`_HERMETIC_SETTINGS_DEFAULTS['oidc_scope']`). No `build_app()` test boots with a scope the product
does not ship. The specific harm F-1 described — the whole suite exercising a retired configuration —
is gone.

**(c) false comment — the old falsehood is gone; a new, subtler one replaced it.** See **F-12**
(LOW). Not a re-open of F-1: nothing is shadowed and no test is misconfigured. It is a coverage claim
the assertion does not support.

**Is the literal pin still a drift trap? Yes — structurally — but keeping the pin was the right
call, and there is a third option you did not weigh that has neither cost.**

The pin is a hand-copied duplicate of `app/core/config.py:63`. The next `oidc_scope` change
re-creates the shadow. What changed materially is the *signal*: at round 1 the drift was silent and
actively mislabelled ("`# settings.oidc_scope default`"); now `test_auth_config.py:95` fails
immediately on any default change and points straight at the value, and the conftest comment states
the invariant in so many words ("It must track `Settings.oidc_scope`'s real default"). The trap
degrades from *silent* to *documented and adjacent to a failing test* — still human-enforced, not
machine-enforced.

Your framing of the tradeoff is correct on the two options you weighed, and **dropping the key would
be the wrong call**: the conftest's own comment eight lines above records a realized incident
(`oidc_redirect_uri`, AUTH-05, 2026-09-08) where a real `.env` value leaked into this fixture and
broke a test that had only ever passed by accident. Env leakage into `_HERMETIC_SETTINGS_DEFAULTS` is
a demonstrated failure mode here, not a hypothetical, so trading hermeticity for drift-resistance is
a bad trade. Preserving the fixture's hermetic purpose was the right instinct.

The third option costs nothing on either axis:

```python
"oidc_scope": Settings.model_fields["oidc_scope"].default,
```

Still a constructor kwarg — env and `.env` are shadowed exactly as they are today, so hermeticity is
byte-identical — but there is no literal left to drift. It is free here: `tests/conftest.py:70`
already imports `from app.core.config import settings` at module scope, so D-07's deferred-import
rule (which exists because `app.main` drags the whole router graph in) does not apply to
`app.core.config`. A one-line `assert` that the pin equals the field default is an equally good
mechanical guard. Carry-forward, not a blocker — the pin as shipped is correct today.

### Anti-suppression and surgical-changes: clean

- **One hunk per file**, both inside F-1's named lines. `git diff main --name-only` is the round-1
  set plus exactly these two files.
- **No test weakened.** `test_auth_oidc_login.py:81` remains an exact list-equality on the full scope
  string — no substring/`in` downgrade, no parametrize-away. Grep of both files for
  `skip`/`xfail`/`filterwarnings`: zero hits.
- **No unrelated reformatting.** Confirmed independently and more broadly than reported:
  `ruff format --check` flags 6 files, of which 3 are Python files AUTH-06 touches
  (`tests/conftest.py`, `tests/unit/test_programs.py`, `app/api/programs.py`). Running the formatter
  against pristine `main` copies (`git show main:…`) produces the **same hunk count and shape** for
  all three — conftest `@@ -169` (1 hunk) at both, `test_programs.py` 4 hunks at both — differing only
  by AUTH-06's line shifts. So every format flag is pre-existing at `main` (ING-10's carry-forward),
  and AUTH-06 as a whole, not just this fix, introduced zero new format drift. `lint:` is
  `ruff check`, which passes clean.

### F-12 — **CLOSED (round 3)** — the replacement comment claimed coverage the assertion did not provide; the fix's two hunks contradicted each other

- Category: testability (test narration accuracy)
- Path: `services/api/tests/unit/test_auth_oidc_login.py:79-83`
- Source: `AUTH-06-AC-6`; review-assessment § File categorisation → truthful claims; the fix's own
  `tests/conftest.py:663-670` comment
- Description: the new comment says this assertion "proves the shipped default actually reaches
  Keycloak's authorization request" and instructs "Keep it reading the default (do not pin a scope
  override on this test)". It does not read the default. `build_app(**_FULL_OIDC_CONFIG)` supplies no
  `oidc_scope` override, so the value comes from `_HERMETIC_SETTINGS_DEFAULTS` **as a constructor
  kwarg** — which the sibling hunk in this very fix correctly describes as "highest precedence, above
  env and the field default". The test is already pinned, at the fixture level. Verified at runtime:
  `Settings(**{**_HERMETIC_SETTINGS_DEFAULTS, 'oidc_scope': 'SENTINEL-SCOPE'}).oidc_scope` →
  `'SENTINEL-SCOPE'`. Consequence: revert `config.py:63` to `"openid profile email groups"` and
  **both** `/auth/login` scope tests stay green; only `test_auth_config.py:95` fails. So AC-6's
  default guard is `test_auth_config.py:95` — the comment demotes it to "checks the `Settings` value"
  while promoting itself — and what line 81 actually guards is "`/auth/login` forwards
  `settings.oidc_scope` verbatim and appends nothing", a property
  `test_login_scope_reflects_configured_oidc_scope` (`:96-105`, `oidc_scope="openid profile"`) already
  covers with an explicit override. This is the same failure mode as the comment it replaced — a
  fixture-supplied value narrated as the product default — one level subtler.
- Severity rationale: LOW, not a re-opened HIGH. Nothing is misconfigured, no test is wrong, no trap
  fires on a future edit. The cost is a reader over-trusting the AC-6 coverage story.
- Suggested fix: reword to what it guards — "`/auth/login` forwards `settings.oidc_scope` verbatim
  and never appends `groups`; the shipped default's *value* is pinned by `test_auth_config.py:95`
  (hermetic, env stripped)". Pair with the self-tracking conftest pin above, which would make the
  comment's original claim true rather than merely reworded.
- **Round-3 resolution: CLOSED.** The second half of the suggested fix was taken — the conftest pin
  now derives from `Settings.model_fields["oidc_scope"].default`, which makes the comment's original
  claim true rather than reworded, exactly as proposed. Re-measured end-to-end: see § Round-3 delta,
  claims 2–5. Hermeticity unchanged byte-for-byte.

### F-13 (NEW, LOW) — the two fixed files are outside `tasks.json` `file_plan`, which is now stale at 16/18

- Category: scope-creep (bookkeeping)
- Path: `services/api/tests/conftest.py`, `services/api/tests/unit/test_auth_oidc_login.py`
- Source: `docs/features/AUTH-06/tasks.json` `file_plan` (F-01..F-16; neither file appears)
- Description: the source diff is now 18 files against a 16-entry declared plan. Both additions are
  review-directed remediation of F-1 and are legitimate — round 1 explicitly ruled them in-PR under
  surgical-changes' "remove what YOUR changes made unused" clause, not carry-forward. Filed only so a
  later scope audit does not read two unexplained files as silent creep.
- Suggested fix: orchestrator action, not a source edit — append them to `file_plan` as F-17/F-18
  annotated "review-directed (REVIEW.md F-1)", or note the exception in the PR body.

### Standing findings — re-confirmed on this snapshot

All nine re-verified by reading the cited code, not by assumption. Line numbers unchanged (the fix
touched no file any of them cites):

| Id | Sev | Location (re-verified) | Status |
|---|---|---|---|
| F-2 | MEDIUM | `program_roster_resolver.py:130` (`async with self._lock`) | Stands |
| F-3 | MEDIUM | `docs/how-to/dev-bypass-auth.md:44-51` | Stands — still documents the deleted `groups` round-trip and `_parse_programs` |
| F-4 | MEDIUM | `program_roster_resolver.py:152` (`wait_for`) | Stands |
| F-5 | MEDIUM | `tests/perf/test_program_roster_resolver_perf.py:121-192` | Stands |
| F-6 | LOW | `app/core/auth.py:252` vs `:228-229` | Stands |
| F-7 | LOW | `app/auth/dev_bypass.py:84` | Stands — `settings` still injected, still unused |
| F-8 | LOW | `program_roster_resolver.py:192` | Stands |
| F-9 | LOW | `program_roster_resolver.py:112-117,138` | Stands |
| F-10 | LOW | `tests/perf/test_program_roster_resolver_perf.py:78,105` | Stands |
| F-11 | LOW | working-tree artefacts | Stands, **amended** — see below |

**F-11 amendment.** The ING-10 artefacts (`docs/features/ING-10/state.json`,
`SECURITY-20260908-1253.md`) and the mutated `docs/activity/activity.jsonl` are all still
uncommitted. Additionally, `.claude/worktrees/` is untracked **and not gitignored** —
`git check-ignore` returns no match — at **2.7 GB**. A `git add -A` on this tree would attempt to
stage it. F-11's "stage AUTH-06's files explicitly" is now load-bearing, not hygiene advice.

The four MEDIUMs are re-confirmed **as graded**. None was re-graded to reach a cleaner verdict.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL |   0   | — |
| HIGH     |   0   | — (F-1 closed round 2) |
| MEDIUM   |   4   | design-patterns (1), integration (1), testability (1), docs (1) |
| LOW      |   8   | safety-and-security (1), module-structure (2 — F-7, F-14), design-patterns (2), reusability (1), scope-creep (2 — F-11, F-13) |

Closed: F-1 (HIGH, round 2), F-12 (LOW, round 3).

Scope-creep in source: 0 substantive (F-13 is bookkeeping on review-directed files).
ADR/decision violations: 0. Contract-drift: 0.

## Detailed findings (rounds 1–2)

### HIGH

#### F-1 — **CLOSED (round 2)** — retirement incomplete in the shared test harness
- Category: safety-and-security (config integrity) / testability
- Path: `services/api/tests/conftest.py:663-664`, `services/api/tests/unit/test_auth_oidc_login.py:81`
- Source: `.claude/rules/surgical-changes.md`; `AUTH-06-AC-6`; implementation flag AF-04
- Round-1 description: (a) `conftest.py:664` still passed `"program_group_prefix": "program-"` as a
  `Settings(...)` constructor kwarg for a field this diff deleted, swallowed by `extra="ignore"` —
  permanently dead config reading as live. (b) `conftest.py:663` pinned the retired
  `"openid profile email groups"` at the highest precedence tier, so every `build_app()` test booted
  with `groups` requested. (c) `test_auth_oidc_login.py:81` asserted the retired value under the
  comment `# settings.oidc_scope default` — factually false, and an active trap that would fail the
  moment anyone completed the retirement.
- Round-2 resolution: all three addressed. (a) and (b) verified closed at runtime. (c) reworded; the
  replacement carries a different inaccurate claim, filed separately and non-blocking as **F-12**.

### MEDIUM

#### F-2 — a single resolver-wide `asyncio.Lock` is held across the DB query, serializing cold misses for *all* emails on the auth critical path
- Category: design-patterns / performance
- Path: `services/api/app/core/program_roster_resolver.py:130-136`
- Source: `.claude/rules/performance-baseline.md`; `REQUIREMENTS.md` NFR (AUTH-04's p95 < 300ms budget)
- Description: `self._lock` is one lock for the whole resolver, held for the duration of
  `_resolve_uncached`. This faithfully mirrors `PersonaResolver` (which FR-2 mandates), but the key
  cardinality is not comparable: `PersonaResolver` keys on ~5 role strings, this keys on every user
  email in the org. A cold miss for email A blocks cold resolution for B, C, … for the query's full
  duration — up to the 3.0s timeout if the DB stalls, at which point one slow query head-of-lines
  every cold session construction org-wide. Measured cold latency (1.99–3.16 ms, AF-06) makes this
  small in steady state; the degraded-DB case is the sharp one. The Condition-1 measurement (T-17) is
  single-threaded and does not cover this profile.
- Suggested fix: no change in this PR — deviating from the mandated precedent needs a decision.
  Carry-forward: either a per-email lock dict (`defaultdict(asyncio.Lock)` with eviction) or an
  explicit accepted-risk entry, plus a concurrent-distinct-email variant of the perf test.

#### F-3 — `docs/how-to/dev-bypass-auth.md` documents a mechanism this diff deleted, and claims it was "verified directly against the shipped code"
- Category: docs (truthful claims)
- Path: `docs/how-to/dev-bypass-auth.md:44-51`
- Source: review-assessment § File categorisation, Docs → "Truthful claims"; implementation flag AF-08
- Description: the how-to states `programs: ["alpha"]` is encoded into the token's `groups` claim as
  `["program-alpha"]` and parsed back by `get_current_user`, and includes a doctest-style
  `>>> _parse_programs(["program-alpha"], "program-")` invoking a function this diff deleted. A
  developer following it will look for a `groups` claim that no longer exists. Drift *this change
  caused*, not pre-existing rot. Correctly not fixed inline: the file is in no `file_plan` entry and
  AC-7's documentation scope names `README.md` only.
- Suggested fix: carry-forward a one-file doc update replacing the groups round-trip with the
  top-level `programs` claim + `kid == DEV_BYPASS_KID` read, and drop the `_parse_programs` snippet.

#### F-4 — the roster-timeout fail-closed 500 is correct but unasserted at the HTTP layer; a future fail-open regression would pass every test
- Category: testability / integration
- Path: `services/api/app/core/program_roster_resolver.py:151-154`; `services/api/app/core/errors.py:28-33`
- Source: `AUTH-06-FR-1`; `.claude/rules/performance-baseline.md`
- Description: fail-closed is the right call and FR-1's "no 401/500" clause is respected — that
  clause is scoped to the zero-row case, which TC-01 asserts explicitly (bob → HTTP 200,
  `programs == []`). `ProgramRosterResolutionError` carries no email, so the catch-all's
  `{"error": {"code": "internal_error", ...}}` leaks nothing, and no retry is added (correct on the
  auth critical path). The gap: `pytest.raises(ProgramRosterResolutionError)` is asserted only at the
  resolver level (`test_auth_groups.py:749`); nothing asserts the request-level outcome. Grep
  confirms no test anywhere asserts a 500 from this path. A future "make it resilient" change
  returning `[]` on timeout would silently strip every user's programs and pass the entire suite.
- Suggested fix: carry-forward one HTTP-level assertion — stalled resolver → 500 with the
  `internal_error` envelope and no `programs` key — pinning fail-closed as the contract.

#### F-5 — Condition-1's p95 is measured against a one-row `program_roster`, so it cannot detect the failure it names
- Category: testability
- Path: `services/api/tests/perf/test_program_roster_resolver_perf.py:142-155,204-213`
- Source: research Condition 1; `.claude/rules/performance-baseline.md`; implementation flag AF-06
- Description: one seeded row means Postgres almost certainly seq-scans rather than using
  `ix_program_roster_email`. The number proves the round trip is cheap, not that the index is used at
  production roster size — while the assertion's own failure message offers "missing/unused
  `ix_program_roster_email`" as a diagnosis it structurally cannot produce. Precedent-consistent with
  `test_persona_resolver_perf.py`'s Tier-3 seed, and D-03's 100ms budget is correctly not loosened.
- Suggested fix: carry-forward a seeded-at-scale variant mirroring `test_programs_perf.py`'s 100-row
  seed, or trim the failure message's index claim to what the test can actually observe.

### LOW

#### F-6 — `list(claims.get("programs") or [])` has no `isinstance(list)` guard, unlike the `groups` read three lines above
- Category: safety-and-security (defense in depth)
- Path: `services/api/app/core/auth.py:252` vs `:228-229`
- Source: `.claude/rules/security-baseline.md`; `.claude/rules/pattern-consistency.md`; flag AF-05
- Description: graded LOW deliberately. The claim is unreachable as anything but `list[str]`: written
  only by `dev_bypass.py` from `DevBypassRequest.programs: list[str] | None` (Pydantic-validated),
  and the token is RS256-signed by a process-local ephemeral keypair no external party can produce,
  resolvable only under AUTH-01's allow-list. The asymmetry with `groups` is arguably *justified* —
  `groups` arrives from Keycloak, `programs` does not. Residual risk is silent if that changes: a
  string claim would char-splat (`"PROG-A"` → `['P','R','O','G','-','A']`).
- Suggested fix: optional —
  `programs_claim = claims.get("programs"); programs = list(programs_claim) if isinstance(programs_claim, list) else []`.

#### F-7 — `settings` is now a dead parameter on `dev_bypass_sign_in`
- Category: module structure & boundaries
- Path: `services/api/app/auth/dev_bypass.py:84`
- Source: `.claude/rules/surgical-changes.md`
- Description: `settings.program_group_prefix` was the handler body's only consumer of `settings`;
  deleting it left `settings: Settings = Depends(get_settings)` injected and unused. Ruff's enabled
  rule set (`E,F,I,UP`) has no unused-argument check, so nothing flags it. Functionally inert.
- Suggested fix: drop the parameter (narrowing the `app.core.config` import if it becomes unused), or
  leave it with a one-line note if signature stability is preferred.

#### F-8 — `program_membership_resolved`'s `timestamp` extra is `...+00:00Z`, an invalid ISO-8601 string
- Category: design-patterns
- Path: `services/api/app/core/program_roster_resolver.py:192`
- Source: `.claude/rules/pattern-consistency.md`; implementation flag AF-01
- Description: verified inert — `JSONFormatter.format` writes its own `timestamp` first and merges
  extras only under `key not in payload` (`app/core/logging.py:44-56`), so the malformed value is
  discarded and never emitted. Copied verbatim from two in-repo precedents (`persona_resolver.py:222`,
  `rbac.py:362`), which is what pattern-consistency prescribes for a new file. Only a cross-file
  change would fix all three.
- Suggested fix: none here. Carry-forward a three-site cleanup.

#### F-9 — `tier=db_query` counts callers that reached the lock, not queries issued
- Category: design-patterns (observability)
- Path: `services/api/app/core/program_roster_resolver.py:112-117,138`
- Source: implementation flag AF-02; `AUTH-06-FR-2`
- Description: two coalesced callers both log `db_query` for one query. Deliberate, documented in the
  method docstring, and required by TC-03's own assertion. Anyone later building a roster-query-rate
  or DB-load metric off this event will overcount.
- Suggested fix: none. Carry the semantics into any future dashboard/alert built on the event.

#### F-10 — `_percentile` now duplicated across 7 perf files, `production_logging` across 6
- Category: reusability
- Path: `services/api/tests/perf/test_program_roster_resolver_perf.py:78-117`
- Source: `.claude/rules/reusability-baseline.md`; implementation flag AF-07
- Description: copied again here as the in-repo precedent requires and the task directed. At 7 and 6
  copies a shared `tests/perf/_helpers.py` is overdue; not fixing it inline was correct under
  surgical-changes (6 sibling files, mid-DAG).
- Suggested fix: carry-forward the extraction as its own chore.

#### F-11 — the working tree carries unrelated uncommitted artefacts that will land in this PR if committed wholesale
- Category: scope-creep (PR hygiene, non-source)
- Path: `docs/features/ING-10/state.json`, `docs/features/ING-10/SECURITY-20260908-1253.md`,
  `docs/activity/activity.jsonl`, `.claude/worktrees/`
- Source: `.claude/rules/surgical-changes.md`
- Description: outside the source-scoped diff, so not a code finding — but ING-10's security-review
  completion (`security: null → "PASS"`, `phase: review → security-reviewed`, plus a carry-forward
  schema migration) and its new SECURITY report are sitting uncommitted alongside AUTH-06.
  Separately, `activity.jsonl` mutates four *historical* rows for unrelated features rather than only
  appending — `AUTH-03`/`AUTH-01`/`ING-01` `/arh-implement` rows have counters rewritten, and ING-01's
  `outcome` flips `completed → error`. Harness telemetry rollup behaviour, not this story's doing, but
  the log is not append-only and a reviewer diffing it sees unrelated churn.
  **Round-2 amendment:** `.claude/worktrees/` is untracked and **not gitignored** (`git check-ignore`
  no match), at **2.7 GB**. `git add -A` would attempt to stage it.
- Suggested fix: stage AUTH-06's files explicitly (never `git add -A` on this tree); commit the
  ING-10 artefacts separately under ING-10; consider gitignoring `.claude/worktrees/`.

### LOW (new in rounds 2–3)

See **F-12** (CLOSED round 3) and **F-13** in the Round-2 delta, and **F-14** in the Round-3 delta
above.

## Answers to round-1's five directed questions

Unchanged by this snapshot; retained for the record.

1. **FR-3 (security core) — clean.** `kid == DEV_BYPASS_KID` at `auth.py:251` is the sole
   discriminator; no second condition is OR-ed on. The branch is reachable only after
   `jwks_cache.get_signing_key(kid)` resolved the dev key (itself 401 unless
   `settings.dev_bypass_enabled`, `jwks.py:152-155`) *and* `jwt.decode` + `claims.validate()` passed
   against the dev-specific essential `iss`/`aud` pair. The inline comment (`auth.py:233-250`) names
   both rejected alternatives with the concrete attack for each and closes with an imperative. It
   would deter a widening, and `test_auth_dev_bypass.py::test_kid_is_sole_roster_skip_discriminator_tc02`
   makes deterrence enforceable: a genuinely signed non-dev `kid` token carrying `programs: ["PROG-Z"]`
   must resolve `[PROG-ROSTER]` from the roster, with a query spy proving exactly one `program_roster`
   SELECT carrying the `removed_at IS NULL` predicate and the session email as a bind param.
2. **AC-8 — verified.** `git diff main --stat -- services/api/app/api/` is empty; no file under
   `app/api/` changed at all. `test_programs.py`'s fixture rewrite keeps that guarantee meaningful.
3. **Scope creep — none substantive.** Round 1: 16/16 against `file_plan`. Round 2 adds the two
   review-directed files (F-13, bookkeeping only). Every comment/docstring edit corrects a statement
   *this diff falsified*.
4. **Fail-closed 500 — right call; FR-1 respected.** FR-1's "no 401/500" is scoped to the zero-row
   case, which returns 200/`[]` and is tested. A timeout is a different case; defaulting to `[]` would
   silently misreport memberships as revoked. Envelope leaks nothing, exception carries no email, no
   retry. Residuals filed: AF-03 (3.0s cancellation on the request-scoped session) and F-4.
5. **AF-05 — LOW, not MEDIUM.** See F-6.

## What went well

- FR-3's discriminator is fortified, not merely implemented — inline rationale naming both rejected
  alternatives, plus a negative test that signs a real token rather than hand-forging one.
- `ProgramRosterResolver` mirrors `PersonaResolver` closely enough to be reviewable by diff, with its
  two deliberate deviations stated in the module docstring.
- D-02 and D-03 are enforced by assertions, not prose: `assert "groups" not in dev_claims` and
  `COLD_P95_BUDGET_MS = 100.0` with a failure message that pre-emptively forbids relaxing it.
- The `test_programs.py` fixture rewrite protects AC-8 from passing for the wrong reason.
- **Round 2:** the F-1 fix is exactly four lines of behaviour across two files, with no collateral —
  no reformatting, no weakened assertion, no new file. The conftest comment correctly identifies
  *constructor-kwarg precedence* as the root cause rather than just changing the string, which is the
  understanding that makes the fix durable.
- **Round 3:** the fix makes the narration true by changing the code, not by trimming the claim — the
  derived pin converts an assertion that only guarded verbatim forwarding into one that guards the
  shipped default, and the comment says exactly that and nothing more. It also names its own
  expiry conditions ("stops guarding … if someone pins a literal or overrides it here"), both of
  which measured true. Third wording, first one that survives experiment.
- The remedy is two lines of behaviour (`:70`, `:673`) with no test weakened, no assertion relaxed,
  no new file, and no reformatting; `ruff`/`mypy`/`pytest` all unchanged.

## Recommendation

**PASS WITH WARNINGS.** No blocker remains, and round 3 found nothing that could produce one. F-1
(round 2) and F-12 (round 3) are both closed on their substance, the latter verified by experiment
rather than by reading: the comment's five claims each measured true, and the hermeticity question
that could have re-graded the remedy upward measured byte-for-byte clean, with both hypothetical
degradations of the derived pin failing loudly rather than silently. The verdict literal holds only
because 4 MEDIUMs exceed the `≤3` PASS threshold — all four are carry-forward design/coverage
observations graded in round 1, none re-graded to reach a cleaner verdict. The 8 LOWs need no code
change to merge; F-13 and the new F-14 are one bookkeeping entry and one dead import. This is the
hard-cap round: nothing here warrants a fourth pass. Proceed to `/arh-security-review`.
