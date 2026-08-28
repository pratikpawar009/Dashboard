# AUTH-01 — Agent flags

Observations agents DECIDED on but want a human to know about. Triaged via `/arh-human-review AUTH-01`.
Ids are assigned by the `/arh-implement` orchestrator (single writer). `status: open` blocks Step 5 (RC4).

### AF-01: `Settings(_env_file=None)` is a mypy error on any BaseSettings subclass

- kind: risky-pattern
- raised_by: T-10
- source: `services/api/app/core/config.py` (`Settings`), surfaced in `services/api/tests/unit/test_auth_config.py`
- status: **accept** (triaged 2026-08-28)

`Settings` subclasses `BaseSettings`, whose metaclass is `@dataclass_transform`-decorated (PEP 681).
mypy therefore synthesises each subclass's `__init__` from declared fields only and drops
`BaseSettings`' private init kwargs — so `Settings(_env_file=None)` fails `call-arg` even though it
works at runtime. T-10 worked around it with a test-only `_HermeticSettings(Settings)` subclass
overriding `model_config = SettingsConfigDict(env_file=None)`. Any future code needing to suppress
`.env` must use the same subclass idiom, not the private kwarg.

**Triage (accept)**: Documented idiom. The `_HermeticSettings` subclass is the supported way to suppress `.env` under PEP 681; no code change warranted.

### AF-02: shared test-DB contention when tasks verify concurrently

- kind: risky-pattern
- raised_by: T-10
- source: shared Postgres test container `bed03-manual` (:5443)
- status: **accept** (triaged 2026-08-28)

One full-suite run during concurrent AUTH-01 task execution showed transient ERRORs in unrelated
DB-backed tests (`test_migrations.py`, `test_rollup_rebuild_*`); not reproducible on two immediate
re-runs (176 passed / 0 failed both times). Root cause is contention, not a code defect:
`tests/conftest.py::migrated_db` runs `alembic upgrade head` / `downgrade base` around EVERY test
against one shared database, so two concurrent `pytest` processes clobber each other's schema.

Orchestrator mitigation applied from Round 4 onward: parallel workers verify with the DB-free
subset (`pytest tests/unit/test_auth_*.py`) plus ruff/mypy; the orchestrator runs the FULL suite
serially between rounds and at the evidence pass, with no sibling workers in flight. AUTH-01 adds
no DB dependency of its own (DATA-DESIGN §1/§2), so no AUTH-01 test is affected either way.
Carry-forward: the suite is not safely parallelisable across processes today — a per-worker
database (e.g. `pytest-xdist` + `TEST_DATABASE_URL` templating) would be needed to change that.

**Triage (accept)**: Mitigated during this run (workers verified against a DB-free subset; the orchestrator ran the full suite serially). Making the suite parallel-safe needs per-worker databases — out of AUTH-01 scope.

### AF-03: `httpx` was a dev-only dependency but is imported by production code

- kind: correctness-defect
- raised_by: T-05
- source: `services/api/pyproject.toml`, `services/api/Dockerfile`, `services/api/app/auth/jwks.py`
- status: resolved-inline

`app/auth/jwks.py` is the first module to `import httpx` in production code (outbound JWKS fetch;
`app/auth/oidc.py` will follow for code exchange and refresh). `httpx>=0.27` was declared only in
`[dependency-groups].dev`, and `services/api/Dockerfile` builds the image with `uv sync --no-dev`
— so once T-06/T-09 wire this module into `app.main`, the container would have failed at boot with
`ModuleNotFoundError: No module named 'httpx'`. Static checks could never catch it: `ruff`, `mypy`,
and `pytest` all run in the dev environment where httpx is present.

Verified before fixing: `httpx>=0.27` was on line 28 inside the dev group; `Dockerfile` runs
`uv sync --no-dev` twice.

**Resolved inline by the orchestrator** (one-line dependency move, `F-10` is in PLAN scope and no
task was in flight against it): `httpx>=0.27` moved to `[project].dependencies` with a comment
recording why. Proven with `uv sync --no-dev && uv run --no-dev python -c "import httpx, authlib"`
→ resolves cleanly (httpx 0.28.1). `respx` correctly stays dev-only. No human action needed; recorded
so the change is traceable to a cause rather than appearing as unexplained drift.

### AF-04: an `asyncio.gather` stampede test needs a real suspension point in the mock

- kind: risky-pattern
- raised_by: T-05
- source: `services/api/app/auth/jwks.py`, applies to `tests/perf/test_auth_jwks_perf.py` (T-20)
- status: **resolved** — acted on by T-20 and independently re-confirmed

A purely synchronous respx mock never yields control, so each "concurrent" coroutine runs to
completion before the next is scheduled — an `asyncio.gather` stampede test then observes N fetches
and looks like a broken lock even when the cache is correct. T-05 hit exactly this false negative
and confirmed the cache is sound only after giving the mocked JWKS response a genuine
`await asyncio.sleep(...)`. T-20 must do the same or its TC-29 assertion is meaningless in both
directions.

Resolved: T-20 independently reproduced the trap before writing its test — a synchronous mock gave
**10** fetches for 10 concurrent calls (a false failure), and adding `await asyncio.sleep(0.05)` to
the mocked response collapsed it to exactly **1**, confirming the lock is correct. The landed
`test_concurrent_unrecognized_kid_requests_collapse_to_single_fetch` uses the async side effect.
Kept as a record because the trap will recur in any future concurrency test.

Note: T-05 also reported test-order flakiness attributed to `pytest-randomly`. **That attribution is
incorrect — `pytest-randomly` is not installed** (verified: `importlib.util.find_spec` → absent), so
its `-p no:randomly` workaround was a no-op. The observed flakiness is AF-02 (shared-test-DB
contention between concurrent workers), already recorded and mitigated.

### AF-05: dev-bypass tokens are rejected by every protected route (story-intent gap)

- kind: architecture-gap
- raised_by: T-08 (confirmed by direct test, not inferred)
- source: `services/api/app/auth/dev_bypass.py` (token issuance) vs
  `services/api/app/core/auth.py::get_current_user` (JWKS-only trust model)
- status: **resolved** — Product decision D-08 taken 2026-08-28, implemented by T-27

`POST /auth/dev-bypass` returns 200 with a well-formed `TokenResponse`, satisfying AC-8's literal
wording. But `get_current_user` verifies every bearer token's signature against Keycloak's real
JWKS, and dev-bypass has no access to Keycloak's private signing key — so the token it issues
**401s against every `Depends(get_current_user)`-protected route**. Verified end-to-end by T-08:
minted a dev-bypass token, called a guarded route, got
`401 {"error":{"code":"http_401","message":"invalid_token"}}`.

Why the existing test suite would not have caught this: TC-08 asserts only that a token is
*issued* with the right shape and zero Keycloak calls. No test case in `docs/test-cases/AUTH-01.json`
exercises a dev-bypass token against a protected route, so all 39 TCs can pass with the feature
functionally broken for its stated purpose.

The gap is against stated story intent, not just a nicety:
- Story user story: "so that developers without a live IdP can still sign in locally via dev-bypass"
- REQUIREMENTS.md § Problem: "Developers also have no way to exercise persona-scoped routes locally
  without a live Keycloak realm"
- PLAN.md § 6 accepts risk R-09 *on the grounds that* "dev-bypass (T-08) covers local dev"
- T-25 is scheduled to write `docs/how-to/dev-bypass-auth.md` documenting local sign-in — which
  would document a flow that does not work

Resolved per `DECISIONS.md` § D-08 (option 2 of `QUESTIONS.md` § Q-02): `app/auth/jwks.py` owns an
ephemeral, process-local RS256 keypair with the reserved kid `dev-bypass-local`, served by
`JwksCache.get_signing_key` **only** when `settings.dev_bypass_enabled`; `dev_bypass.py` signs with
the private half. Verification still flows through the single existing JWKS path — no second trust
branch was added to `get_current_user`.

Verified by T-27: the same token returns 200 on a guarded route under `development`, and 401 under
`production`, `staging`, and `produciton`; a real Keycloak-kid token still verifies with exactly one
JWKS fetch; a dev-kid lookup makes zero outbound calls. Pinned going forward by TC-40 (T-16).

### AF-06: a group named exactly `program-` yields an empty-string program id

- kind: risky-pattern
- raised_by: T-14
- source: `services/api/app/core/auth.py:100-102` (`_parse_programs`)
- status: **resolved** — Product decision D-10 taken 2026-08-28; implemented by T-26, test flipped by T-28

`_parse_programs(["program-"], "program-")` returns `[""]` — the bare prefix trivially
`startswith` itself and the stripped remainder is empty, so an empty-string entry enters
`CurrentUser.programs`. AUTH-01-FR-5 does not explicitly disallow it, so this is not a spec
violation, but an empty-string program id is unlikely to be meaningful to AUTH-03's downstream
program-scoping checks and more plausibly indicates a malformed IdP group name.

T-14 asserted the ACTUAL current behaviour rather than fixing it (`app/core/auth.py` was outside
its file scope) — `test_bare_prefix_group_parses_to_empty_string_program_entry`. If the decision is
to drop zero-length remainders, that test flips to asserting `[]` and `_parse_programs` gains one
condition.

Resolved per `DECISIONS.md` § D-10: zero-length remainders are dropped, so `["program-"]` → `[]`
while the raw `groups` field still retains the entry verbatim. T-28 renamed and re-asserted the test
(`test_bare_prefix_group_is_dropped_from_programs_but_kept_in_groups`), which now also pins that
`groups` retention — the distinction that matters.

### AF-07: OAuth `state` is generated but never verified — CSRF gap on the authorization-code flow

- kind: security-gap
- raised_by: T-07
- source: `services/api/app/auth/oidc.py` (login redirect / callback)
- status: **defer** (triaged 2026-08-28) — needs a decision before pilot rollout

`/auth/login` generates a per-request `secrets.token_urlsafe(24)` `state` and includes it in the
redirect, but the cookie-less, store-less architecture has nowhere to persist it, so `/auth/callback`
accepts `state` and verifies it against nothing. An attacker-initiated authorization code can
therefore be relayed into a victim's callback. This is inherent to the bearer-only topology
(`docs/requirements/auth.md` § session forbids a FastAPI-set cookie and any server-side session
store), not a coding error — the constraint and the CSRF control are in genuine tension.

Not covered by any test case; no AC or NFR mentions `state` or CSRF for this flow.
Candidate resolutions: a frontend-owned per-flow nonce (the frontend already holds tokens
server-side, so it has somewhere to put one), or PKCE (`code_challenge`/`code_verifier`), which
Keycloak supports and which needs no server-side state on the FastAPI side.

**Triage (defer)**: Product decision D-12: PKCE is the intended fix but is a design change beyond AUTH-01 ACs. Must be resolved before the pilot rollout, not before merge. Tracked as pending carry-forward.

### AF-08: no `oidc_redirect_uri` setting — callback URL is derived from the request

- kind: config-gap
- raised_by: T-07
- source: `services/api/app/auth/oidc.py` (login), `services/api/app/core/config.py`
- status: **resolved** — Product decision D-11 taken 2026-08-28; implemented by T-29

AUTH-01-FR-1's pinned field list has no `oidc_redirect_uri`, so T-07 derives it dynamically via
`request.url_for("oidc_callback")`. Keycloak clients normally register an exact redirect URI, and a
derived value will not match once the API sits behind a reverse proxy or load balancer unless
`X-Forwarded-Proto`/`Host` are correctly forwarded and Starlette is configured to trust them. Works
in local dev and in the tests; a likely failure at pilot deployment.

Resolved per `DECISIONS.md` § D-11: `Settings.oidc_redirect_uri: str | None = None` is used verbatim
when set and falls back to the derived value when unset/empty, so nothing changes locally. T-29 found
`redirect_uri` is produced at TWO call sites — the authorization redirect and the token-exchange POST
— which OAuth requires to match exactly; both now resolve through one shared helper. Verified against
a live server: with the override the `Location` carries the configured URI, without it the derived
host value. `OIDC_REDIRECT_URI` added to `.env.example` (empty = derive).

### AF-09: `_peek_kid` is duplicated between `oidc.py` and `core/auth.py`

- kind: duplicate-logic
- raised_by: T-07
- source: `services/api/app/auth/oidc.py::_peek_kid`, `services/api/app/core/auth.py::_peek_kid`
- status: **defer** (triaged 2026-08-28)

~10 lines of unverified-JWT-header parsing exist in both modules; `core/auth.py`'s copy is private
and was outside T-07's file scope. Violates `.claude/rules/reusability-baseline.md` (DRY across
modules of the same concern). Extract to a shared helper (e.g. `app/auth/jwt_utils.py`) in a
follow-up — deliberately not done inline, per `.claude/rules/surgical-changes.md`.

**Triage (defer)**: Small cleanup: extract the duplicated `_peek_kid` into a shared helper. No behavioural impact; deliberately not bundled into a verified story (surgical-changes).

### AF-10: `/auth/refresh`'s request model lives in `oidc.py`, not `schemas/auth.py`

- kind: inconsistency
- raised_by: T-07
- source: `services/api/app/auth/oidc.py::_RefreshRequest`
- status: **defer** (triaged 2026-08-28)

`app/schemas/auth.py` (F-02) holds `TokenResponse` and `DevBypassRequest`; the refresh request body
model was defined locally because `schemas/auth.py` was outside T-07's file scope. Minor
inconsistency with the codebase's schema-location convention; relocate in a follow-up.

**Triage (defer)**: Small cleanup: relocate `_RefreshRequest` into `app/schemas/auth.py`. No behavioural impact.

### AF-11: two behaviours are implemented but pinned by no test case

- kind: test-coverage-gap
- raised_by: orchestrator (verified against `docs/test-cases/AUTH-01.json`)
- source: `docs/test-cases/AUTH-01.json`
- status: resolved-inline — TC-40 and TC-41 appended

T-13 reported that its brief described TC-17 as an expired-token case, but TC-17 is actually
claim-to-field mapping. Verified: **no test case covers an expired ACCESS token** being rejected on
a protected route (TC-07 covers an expired *refresh* token on the refresh route — a different route
and a different failure path). Combined with AF-05's finding that no TC exercises a dev-bypass token
against a protected route, the 39-case set could pass with two significant behaviours unproven.

Both gaps closed by appending TC-40 (dev-bypass token accepted on a protected route, per D-08) and
TC-41 (expired access token → 401), with `coverage_audit` updated. T-13 had already written the
expiry test defensively without a TC id to bind to; TC-41 gives it one.

### AF-12: `.env.example` placeholders defeated the documented default-disabled state

- kind: correctness-defect
- raised_by: T-23
- source: `services/api/.env.example`
- status: resolved-inline

REQUIREMENTS.md contradicts itself here. § Documentation requirements says `.env.example` gains the
OIDC vars "as `<PLACEHOLDER>` values"; § Rollout plan defines the feature flag / backout mechanism as
the *absence* of `oidc_client_id`/`oidc_client_secret`/`oidc_issuer` ("unset, the OIDC route is
disabled (501) ... unset the three OIDC config vars to revert without a redeploy").

A literal `<PLACEHOLDER>` string is non-empty, so `Settings.oidc_configured` returns **True**. A
straight `cp .env.example .env` therefore produced a *configured* app that would redirect
`/auth/login` at the real Apexon issuer with junk credentials — while the file's own adjacent
comment claimed the routes would return 501. Verified before fixing.

**Resolved inline by the orchestrator**: `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` are left EMPTY,
with the expected shape shown in a comment above them. This satisfies both clauses — the variables
are documented and no credential is committed (§ Documentation requirements), and "unset" genuinely
means unset (§ Rollout plan). `OIDC_ISSUER` keeps its real non-secret value, which is harmless
because `oidc_configured` requires all three. Proven: sourcing the file and constructing `Settings()`
yields `oidc_configured = False`.

### AF-13: `oidc_realm` is declared and tested but never read

- kind: dead-code
- raised_by: T-23
- source: `services/api/app/core/config.py` (`oidc_realm`)
- status: **accept** (triaged 2026-08-28)

`oidc_realm` is mandated by AUTH-01-FR-1's field list and is covered by `test_auth_config.py`, but no
module reads it — `app/auth/oidc.py` and `app/auth/jwks.py` both derive their endpoints from
`oidc_issuer`, whose URL path already contains the realm (`.../realms/Apexon`). Not a defect (FR-1
specifies the schema, and the field is implemented as specified), and deliberately NOT removed here
since a requirement pins it. Worth confirming whether it is reserved for future use or should be
dropped from FR-1.

**Triage (accept)**: `oidc_realm` is mandated by AUTH-01-FR-1 and implemented as specified; unread today because the realm is embedded in the issuer URL. Removing it would contradict an approved requirement.

### AF-14: dev-bypass tokens are per-process, so multi-worker deployments will reject them

- kind: operational-constraint
- raised_by: T-24 (discovered empirically — a cross-process curl 401'd)
- source: `services/api/app/auth/jwks.py` (process-local dev keypair, D-08)
- status: **accept** (triaged 2026-08-28) — documented, no code change proposed

D-08's dev signing key is generated once **per process** and never persisted. T-24 confirmed the
consequence by accident: a dev-bypass token minted by one uvicorn process 401s when presented to a
different process. Within one running process it round-trips correctly (verified: dev-bypass 200 →
guarded route 200 with role/groups/programs intact).

Two practical implications, documented in `services/api/README.md` § Auth and `docs/how-to/dev-bypass-auth.md` § 2:
- tokens do not survive an API restart (including `uvicorn --reload` reloads);
- if the API is ever run multi-worker (`uvicorn --workers N`, gunicorn) or multi-instance, each
  worker holds a different key, so a dev-bypass token will 401 on whichever worker did not mint it.

Not a defect — it is the direct, intended consequence of choosing an ephemeral key over a committed
static one (D-08 rejected a committed key precisely because it would be a real credential in source).
The current `Dockerfile` CMD runs a single uvicorn process with no `--workers`, so nothing ships
broken today. Worth revisiting only if dev-bypass is ever needed against a multi-worker local stack.

Correction (orchestrator): this entry originally claimed both implications were already in
`services/api/README.md`. T-25 checked and only the restart and production-rejection cases were
there — the multi-worker one was not. The missing line has since been added to that README, so the
claim above now holds; it did not when first written.

**Triage (accept)**: Inherent, intended consequence of D-08 choosing an ephemeral key over a committed one. Documented in `services/api/README.md` § Auth and `docs/how-to/dev-bypass-auth.md` § 2. The Dockerfile runs a single uvicorn process, so nothing ships broken.

### AF-15: design_check dimension marked N/A — no a11y/console-scan/perf tool wired

- kind: evidence-na
- raised_by: implementation-agent (evidence pass)
- source: `docs/config/project-commands.yaml` (`design_check:`)
- status: **accept** (triaged 2026-08-28)

`design_check:` is empty in `project-commands.yaml` — no accessibility/console-error-scan/perf tool
has been declared or installed repo-wide (design integration is `html-mockup`, `fileKey`/`url` still
TODO in `docs/design/schema.json`). Legitimate N/A for AUTH-01 specifically: `design: "n/a"` in
`docs/features/AUTH-01/state.json`, no DESIGN.md, backend-only feature with no UI surface touched.
Same N/A applies repo-wide regardless of story (see BED-01 AF-09, BED-02 AF-07, BED-03 AF-03) —
raised again here per the evidence-pass skill's "never mark N/A without a flag" rule. Note: the
`compile` dimension is NOT N/A for this story — `build:` is non-empty (repo-wide, points at
`apps/web`), so per the anti-gaming rule (applicability is repo-config-driven, not story-scoped) it
was run for real: `pnpm -C apps/web build` succeeded, exit 0 (see `evidence/compile.log`).

**Triage (accept)**: Legitimate N/A: `design_check` is unset in project-commands.yaml and AUTH-01 is backend-only (`design: "n/a"`, no DESIGN.md, no UI surface).
