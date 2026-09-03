# Feature: ING-01 — Ingest token minting + bearer auth

## Problem

Developers and CI/automation clients cannot push their own AI activity data into the platform today. The only authentication path is AUTH-01's interactive Keycloak OIDC flow, which requires a browser and a human session — unusable for a non-interactive script or CI job. Without a machine-scoped credential, either a human must proxy every write on the automation's behalf, or the automation is handed broader session access than it needs. BED-01 already ships the `ingest_tokens` table; nothing mints or validates a token against it yet.

## Outcome

A developer or ops operator runs a CLI script and receives a bearer credential exactly once. That credential, presented as `Authorization: Bearer <token>` to a future `/ingest/*` route (wired in ING-02), is resolved by SHA-256 hash against `ingest_tokens` and either authorized for the requested `program_id` or rejected with a classified 401/403. ING-02, ING-03, and ING-07 can build against a locked `ingest-token-auth` contract (`docs/requirements/auth.md`) — function shape, scope semantics, and log-event schema fixed by this PRD.

## Constraints

- Python 3.11+, FastAPI 0.115, SQLAlchemy 2.0 `AsyncSession`, stdlib `hashlib` / `secrets` / `argparse` only — no new runtime or dev dependency (ADR-0006 §2; `services/api/pyproject.toml` unchanged).
- Upstream: BED-01's `ingest_tokens` table (`services/api/app/models/ingestion.py:62-80`) is complete and merged — `token_hash` (unique), `label`, `user_email`, `allowed_program_ids` (`ARRAY(String) NOT NULL`), `expires_at`, `revoked_at`, `last_used_at`. No schema migration in this story.
- `.claude/rules/security-baseline.md` § Auth tokens (CSPRNG ≥ 32 bytes) binds on `**/*.py` and supersedes story `docs/stories/ING-01.md` AC-1's 24-byte figure — settled by ADR-0006 §1. The story file is not re-edited (`Status: Validated`); this PRD and ADR-0006 are authoritative on the byte count.
- ADR-0006 is authoritative on token format (§1), mint surface (§2), scope semantics (§3), and lifetime (§4) — this PRD encodes those decisions, it does not re-open them.
- Produces the `ingest-token-auth` contract (`docs/requirements/auth.md`) consumed by ING-02, ING-03, ING-07 directly (ING-04, ING-05, ING-06, ING-09 transitively) — function shape, scope-check order, and log-event name are locked from this PRD forward; a post-gate rename requires a coordinated migration across all 7 consumers.
- No HTTP mint route in this story — minting is local-shell-plus-database-credentials only (ADR-0006 §2 rationale); `/ingest/*` route wiring is ING-02's scope.
- No UI surface: project-wide `integrations.design = html-mockup`, but the ING epic has no entry in `docs/design/schema.json` § `designSystem.pages.features` — `design_mode = none` for this story per CLAUDE.md § Design system. `## Screen inventory` is omitted; `## Visual spec` states not-applicable.

## Solution sketch

A standalone CLI script mints a CSPRNG bearer token, persists only its SHA-256 hash plus label/owner/scope metadata, and prints the raw value to stdout exactly once. A second, structurally isolated auth dependency resolves that bearer token by hash on every request: it rejects a missing, unknown, revoked, or expired token with a classified 401, and rejects an in-scope-but-wrong-program request with 403 — scope defaulting to allow-all when the caller supplies none, per ADR-0006. Neither path shares code or route wiring with AUTH-01's Keycloak-JWT session dependency.

## Addressing Research Conditions

Research verdict: GO-WITH-CONDITIONS, 76/100, 5 numbered conditions from `docs/research/ING-01.md` § Conditions for GO.

- **C-1 (Minting surface, CRITICAL)** — Settled by ADR-0006 §2 and encoded in **ING-01-FR-2**: stdlib `argparse` in a standalone script, `services/api/scripts/mint_ingest_token.py`, run as `uv run python scripts/mint_ingest_token.py`. No new dependency; authority to mint is local shell access plus `DATABASE_URL` credentials — no network-reachable mint surface exists to gate. Default TTL settled by ADR-0006 §4 (null, never expires) and encoded in **ING-01-FR-1**.

- **C-2 (Wildcard program scope representation, HIGH)** — Settled by ADR-0006 §3 and encoded in **ING-01-FR-3**: the wildcard is the single array element `["*"]`; an empty array is allow-all. Check order (empty → pass; `"*"` present → pass; membership → pass; else 403) is specified exactly, with test-case anchors for both the specific-id array and the wildcard array left to Phase 2 (`test-case-generation` § Coverage minimum, keyed to this FR).

- **C-3 (Logging event field allowlist, MEDIUM)** — Settled and encoded in **ING-01-FR-5**: `ingest_token_auth_failed` required = `{token_id, reason, program_id, timestamp}`, optional = `{}`. `user_email`, the raw token, and the full hash are omitted per `.claude/rules/security-baseline.md` § Core (no PII, no credentials in logs). Field-set validation at log time mirrors AUTH-03-FR-2's pattern.

- **C-4 (Dependency isolation, MEDIUM)** — Settled and encoded in **ING-01-FR-6**: ingest routes depend on `get_ingest_token()` only, user-session routes depend on `get_current_user()` only, no route declares both. `AsyncSession` injection mirrors the existing dependency pattern; a unit test on a mock dual-dependency route demonstrates the two paths resolve independently.

- **C-5 (Test surface, MEDIUM)** — Addressed structurally: **ING-01-FR-1..FR-6** give Phase 2's `test-case-agent` concrete `requirement_id` anchors for story AC-1..AC-5 — mint output/format and storage (AC-1, AC-2), valid/revoked/expired token resolution (AC-3, AC-4), and program-scope enforcement including wildcard and empty-array edge cases (AC-5, FR-3). Per `test-case-generation` § Scope, the mint script and the SHA-256 hash-lookup helper are unit-shaped internal contracts tracked as `pytest` entries in `docs/features/ING-01/tasks.json` (Phase 3), not the behavioural TC manifest; the field-allowlist assertion (FR-5) and the dual-dependency non-interference check (FR-6) are `type: security` / `type: integration` TCs against the real DB, no mocks at the integration boundary. No E2E TC — no UI surface (story § Test mapping).

## Scope

**In:**
- `services/api/scripts/mint_ingest_token.py` — argparse CLI; mints a token, writes one `ingest_tokens` row, prints the raw token once (ING-01-FR-1, ING-01-FR-2).
- Bearer-token auth-check dependency (`get_ingest_token()` or equivalent) — hash lookup, revoked/expired classification, resolved-record return (ING-01-FR-4).
- Program-scope check helper — empty/wildcard/membership order (ING-01-FR-3).
- `ingest_token_auth_failed` structured log event with the ING-01-FR-5 field allowlist.
- Structural dependency isolation from `get_current_user()` (ING-01-FR-6) — no route uses both.
- Locking the `ingest-token-auth` contract's function shape, scope semantics, and log-event schema for ING-02/03/07.

**Out:**
- `/ingest/*` route wiring and request handling — deferred to ING-02.
- Token listing, revocation, or rotation UI/API — deferred to ING-03.
- Token inventory / observability tooling (list active tokens, flag unscoped tokens, report token age) — explicitly out of ING-01's scope per ADR-0006 § Flagged gaps; carried forward as a candidate follow-up story.
- The manual/webhook ingester and its own CLI framework choice — deferred to ING-06 (free to adopt a richer framework independently, ADR-0006 §2).
- An HTTP-exposed mint endpoint or RBAC-gated admin minting UI — no such surface exists in this story; ADR-0006 §2's authority model is local shell + database credentials only.
- Automatic token expiry or a default TTL — `expires_at` stays null unless a future story changes it (ADR-0006 §4).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/ING-01.md` for canonical wording. New impl constraints introduced below (when any):

**ING-01-FR-1** — Token generation, format, and storage *(supersedes AC-1's byte count; extends AC-1/AC-2 with exact entropy, hashing, and persisted fields)*

Raw token = `hrn_pat_` + `secrets.token_hex(32)` (32 CSPRNG bytes → 64 lowercase hex chars). Per ADR-0006 §1, this supersedes AC-1's 24-byte/48-hex-char figure: `.claude/rules/security-baseline.md` § Auth tokens (CSPRNG ≥ 32 bytes) binds and wins over the un-superseded story spec. The persisted value is `hashlib.sha256(raw_token.encode()).hexdigest()` (64 hex chars) in `ingest_tokens.token_hash` (unique). The row additionally stores `label`, `user_email`, `allowed_program_ids`, with `expires_at = null` and `revoked_at = null` at mint (ADR-0006 §4). The raw token is written to stdout exactly once and is never persisted, logged, or derivable from `token_hash`.

**ING-01-FR-2** — Mint script entry point, inputs, and exit behavior *(extends AC-1 with exact surface and failure mode)*

`services/api/scripts/mint_ingest_token.py`, stdlib `argparse`, invoked `uv run python scripts/mint_ingest_token.py` (ADR-0006 §2). Required inputs: `label` (str), `user_email` (str), and a program scope — one or more program ids, or the literal wildcard `*`. On success: prints the raw token to stdout exactly once, writes one `ingest_tokens` row (ING-01-FR-1), exits `0`. On a missing or invalid argument, `argparse`'s own usage-error path applies — exits non-zero, no DB write attempted, no token printed. No new dependency is introduced; the script behaves identically whether the environment was built with `uv sync` or `uv sync --no-dev` (ADR-0006 §2 rationale, flag AF-03 precedent).

**ING-01-FR-3** — Program scope storage and check order *(extends AC-1/AC-3/AC-5 with exact wildcard representation and empty-array semantics)*

`allowed_program_ids` stores the wildcard as the single array element `["*"]` — the schema has no sibling column for it. An **empty array is allow-all**, not deny-all (ADR-0006 §3). Given a resolved, active token record and a requested `program_id`, the check evaluates in order and stops at the first pass:

1. `allowed_program_ids == []` → pass (unscoped).
2. `"*" in allowed_program_ids` → pass (explicit wildcard).
3. `program_id in allowed_program_ids` → pass (membership).
4. Else → `HTTPException(status_code=403)`.

**ING-01-FR-4** — Auth-check outcome classification *(extends AC-3/AC-4/AC-5 with exact 401/403 branching)*

The auth-check dependency SHA-256-hashes the bearer token and looks up `ingest_tokens.token_hash` (unique index):

| Condition | Outcome |
|---|---|
| No `Authorization` header, or non-Bearer scheme | `401`, `reason=missing` |
| Hash has no matching row | `401`, `reason=unknown` |
| Row found, `revoked_at is not null` | `401`, `reason=revoked` |
| Row found, `expires_at is not null and expires_at <= now()` | `401`, `reason=expired` |
| Row found, active, ING-01-FR-3 scope check fails | `403`, `reason=scope` |
| Row found, active, ING-01-FR-3 scope check passes | resolves the token record; authorized |

`program_id` is supplied by the caller's own request (per AC-3) — never read off the token record.

**ING-01-FR-5** — `ingest_token_auth_failed` log event field allowlist *(Research Condition 3; extends the story's Observability NFR with an exact, enforced field set)*

| Field set | Fields |
|---|---|
| Required | `{token_id, reason, program_id, timestamp}` |
| Optional | `{}` |

`reason` is one of the literal strings `missing \| unknown \| revoked \| expired \| scope` (ING-01-FR-4's five denial branches). `token_id` is `ingest_tokens.id` (UUID) — never the raw token, `token_hash`, or a hash prefix; `user_email` is never included, per `.claude/rules/security-baseline.md` § Core. Emitted once per denial, at the point ING-01-FR-4 or the scope check raises; never emitted on success (mirrors AUTH-03's denial-only `*_view_denied` events). A dedicated test asserts the logged payload's key set equals `{token_id, reason, program_id, timestamp}` exactly — pattern: AUTH-03-FR-2 / `tests/unit/test_persona_resolver.py::test_persona_mapping_loaded_event_contains_no_pii_tc15`.

**ING-01-FR-6** — Auth-path dependency isolation *(Research Condition 4; extends AC-3/AC-4/AC-5 with an explicit non-interference contract)*

Ingest routes depend on `get_ingest_token()` only; user-session routes depend on `get_current_user()` (AUTH-01) only — no route declares both. `get_ingest_token()` takes an injected `AsyncSession`, the same DI seam `get_current_user()` and AUTH-03's checks already use, keeping the two paths structurally independent (neither reads the other's principal type). A unit test wires a mock route carrying both dependencies and asserts they resolve independently — a valid ingest token does not satisfy `get_current_user()`, and a valid Keycloak JWT does not satisfy `get_ingest_token()`.

## Non-functional requirements

- Performance: token verification (SHA-256 hash + indexed `token_hash` lookup + ING-01-FR-3 scope check) adds **p95 < 10ms** to request latency — assumption; the story's Decision log (2026-08-26) records the qualitative rationale (indexed O(1) lookup) without a number, this PRD picks a concrete ceiling consistent with it, in the same class as AUTH-03-FR's `< 5ms p95` per-check budget with headroom for the extra DB round trip an in-process RBAC check does not need.
- Security: Per `.claude/rules/security-baseline.md`: raw token never stored or logged (ING-01-FR-1), CSPRNG ≥ 32 bytes (ING-01-FR-1, ADR-0006 §1), no PII in the `ingest_token_auth_failed` event (ING-01-FR-5). **Accepted risk, not open** (ADR-0006 § Consequences): an empty `allowed_program_ids` grants every program, and a token with no explicit `expires_at` never expires — the most permissive credential this story can issue is also the one produced by omitting a mint flag, and it inverts the fail-closed default AUTH-01/AUTH-03/AUTH-04 use elsewhere. No compensating detection control ships in ING-01; `/arh-security-review` is expected to re-raise this against the ADR, not discover it fresh.
- Accessibility: N/A — backend CLI + auth-check library, no UI surface.
- Observability: one structured JSON log event, `ingest_token_auth_failed`, per ING-01-FR-5, emitted at `logging.INFO` (an ordinary classified deny, not an operational failure — no resolver-timeout-equivalent failure mode exists on this path). No event on a successful auth check, matching NFR-011's precedent that routine authorization is not itself a logged event.
- Reliability: fail-closed on every classified branch in ING-01-FR-4 (401) and the ING-01-FR-3 scope check (403) — zero default-permit outcomes for a token that fails hash lookup, revocation, or expiry. The scope-default and lifetime-default exceptions to fail-closed are named explicitly under Security above, not silently inherited here.

## Visual spec

Not applicable — `integrations.design = html-mockup`, but the ING epic has no entry in `docs/design/schema.json` § `designSystem.pages.features`. Backend CLI + auth-check library, no UI surface.

## Rollout plan

- **Strategy**: bang-bang. ING-01 ships a mint script and an auth-check library with no route surface of its own — `/ingest/*` wiring (ING-02) is a separate story's rollout to coordinate.
- **Feature flag**: none — the script and library are always available once merged; no route calls `get_ingest_token()` until ING-02 ships.
- **Backout plan**: revert the PR. No schema migration (BED-01's `ingest_tokens` table is unchanged); any token already minted during the window stays valid (queryable by hash) but unreachable, since no route resolves it until ING-02 wires one.
- **Success signal**: ING-02's first `/ingest/*` route returns the expected 200/401/403 per ING-01-FR-4/FR-3 against a token minted by this story's script, and its `ingest_token_auth_failed` events appear with exactly the ING-01-FR-5 field set — zero PII-audit-test failures. Carry forward: token-inventory tooling (ADR-0006 § Flagged gaps) has no success signal here because it ships in a later story, if scheduled.

## Documentation requirements

- **README updates**: `services/api/README.md` — new section documenting the mint script's invocation and arguments, the `ingest-token-auth` bearer contract (mirrors the existing `/auth/*` API table's style), and the scope/lifetime defaults from ADR-0006 §3-4.
- **Runbook**: none — revocation and rotation procedures are ING-03's scope; this story's only operational lever is running the mint script, which the README covers.
- **API reference**: N/A — no HTTP route ships in this story; `docs/requirements/auth.md` § `ingest-token-auth` is the machine-readable contract ING-02/03/07 consume.
- **Inline code comments**: module docstring on the auth-check module covering the empty-array-means-allow-all semantics (ING-01-FR-3) and the accepted-risk note from ADR-0006 § Consequences, so a future reader does not mistake the permissive default for a bug — pattern: AUTH-03-FR-3's module-docstring precedent for a deliberate, non-obvious default.
- **Examples / how-to**: none — `docs/requirements/auth.md` § `ingest-token-auth` already documents the call shape for the three downstream consumer stories.

## Open questions

<!-- None open. needs_clarification_count: 0. Zero [NEEDS CLARIFICATION] markers in    -->
<!-- this PRD. All four research clarifications (C-1..C-4, including the token-entropy  -->
<!-- conflict found during resolution) were resolved 2026-08-31 via ADR-0006; see       -->
<!-- docs/research/ING-01.md § Clarification Resolutions. No new ambiguity surfaced     -->
<!-- during drafting. Decisions logged in docs/stories/ING-01.md § Decision log.        -->
<!--                                                                                   -->
<!-- Kept as a comment deliberately, matching AUTH-02/AUTH-04: the phase-preconditions  -->
<!-- clarification gate treats ANY non-blank, non-comment line in this section as an    -->
<!-- unresolved open question and aborts the next phase. Prose saying "None" trips it.  -->

## Approvals

- **2026-08-31** — Pratik Pawar (PO): **APPROVE**
  - Problem, Outcome, and `ING-01-FR-1`..`FR-6` reviewed
  - UI specs reviewed in `DESIGN.md`: N/A — `design = n/a`, backend-only feature (ING epic has no entry in `docs/design/schema.json` -> `designSystem.pages.features`)
  - Edge Cases, Open Questions (0 open), and test-case completeness/automation feasibility reviewed
  - No-placeholder check OK - `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO-WITH-CONDITIONS, 76/100 (all 5 conditions addressed in § Addressing Research Conditions)
  - Four research clarifications settled before the gate as **ADR-0006** and reflected in `docs/requirements/auth.md` § `ingest-token-auth`: 32-byte entropy, `argparse` mint script, wildcard `["*"]` with empty-array-means-allow-all, and `expires_at` null by default.
  - **Accepted risk, reviewed at gate**: `FR-3`'s empty-array-allow-all and `FR-1`'s null `expires_at` compound — the credential produced by omitting a mint flag is the most permissive one the system can issue, and it never expires. `ING-01-TC-06` asserts the allow-all branch as correct behaviour, so the default is now locked in by test. Accepted per ADR-0006 § Consequences; token-inventory tooling stays out of scope (ADR-0006 § Flagged gaps).
  - **Carry-forward**: `docs/stories/ING-01.md` AC-1 still names 48 hex chars / 24 bytes. The story is `Status: Validated` and was deliberately not edited (re-opening forces re-validation); this PRD plus ADR-0006 are authoritative on token format.
  - **Carry-forward (cosmetic, do not fix inline)**: § Addressing Research Conditions labels the five research conditions `C-1..C-5`, colliding with the research doc's `C-1..C-4` clarification labels; its `C-5` bullet also cites `docs/features/ING-01/tasks.json (Phase 3)`, which is a `/arh-plan-implementation` artifact.
  - Test cases: 24 total, 24 automatable, `coverage_audit.uncovered=[]`
  - Tracker subtask: pratikpawar009/Dashboard#153
