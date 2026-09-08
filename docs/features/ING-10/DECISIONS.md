# ING-10 — Decisions

Story-level decision log. `docs/requirements/api.md#program-manifest-api` /
`docs/requirements/data.md#program-roster-schema` already settle the wire contract and table shape;
entries here cover implementation-surface choices those contracts leave open.

### D-01: `program_roster` new additive table (#19), separate from `program_members` · blast:data · rev:effectively-irreversible · adr:ADR-0010

**Context**: `docs/requirements/data.md#program-roster-schema` and RTM Decisions 2026-09-08 already
settle that this story adds a new table rather than upserting `program_members` (which
`rollup_rebuild.py:360,370` unconditionally deletes/rebuilds with no prior-state carry-forward).
This is a durable-schema change other stories (`AUTH-06`) will build against, and once real
programs push manifests, dropping the table loses membership history with no other source of
truth — both the `blast:data` and `rev:effectively-irreversible` promotion triggers fire.

**Decision**: `program_roster` ships via its own additive Alembic revision
(`003_program_roster.py`, chained after `002_personal_usage_indexes`), fully documented in
ADR-0010 — see that ADR for the table shape, the `index(email)` addition anticipating `AUTH-06`'s
read pattern, and the consequences of keeping it separate from `program_members`.

### D-02: New dedicated router `app/api/manifest.py`, registered directly in `app/main.py` · blast:service · rev:mechanical · adr:—

**Context**: `app/api/ingest.py`'s existing `router` is deliberately NOT registered in
`app/main.py` — it is an unauthenticated scaffold stub (`_persist()` fabricates an id and never
writes to Postgres) that PR #235's comment explicitly reserves for `ING-02` to register once that
story's route actually authenticates and persists. Adding `POST /api/ingest/manifest` to that same
`router` object and then registering it would silently re-expose `/ingest/events` — an
unauthenticated endpoint that answers `201` while discarding every event posted to it — as a side
effect of this story, which is not this story's call to make.

**Decision**: `POST /api/ingest/manifest` lives on its own `APIRouter(prefix="/api/ingest",
tags=["ingest-manifest"])` in a new module, `app/api/manifest.py`, authenticated via
`Depends(get_ingest_token)`. `app/main.py` gets one new `app.include_router(manifest_router)` line,
placed among the other always-registered routers; the comment block explaining why
`ingest_router` (from `app/api/ingest.py`) stays unregistered is left untouched — `ING-02` still
owns that decision.

### D-03: Role-slug → persona mapping stays in-process, `ING-10`-scoped only · blast:feature · rev:mechanical · adr:—

**Context**: research risk #3 floated adding a DB-backed `role_mapping` table (parallel to
`persona_config`) so `ING-08`'s Keycloak writer could eventually share it. The PRD/RTM accepted the
in-process-only scope as an author assumption, not a fresh confirmation — wiring `ING-08` onto a
shared table remains an undecided scope change to an already-shipped story, not something this
story should force by building the persistence layer speculatively.

**Decision**: `app/core/role_map.py` is a plain in-process module-level `dict[str, str]`
(`dev→developer, arch→architect, pm→product-manager, em→engineering-manager, cxo→cio,
board_member→cio, admin→cio`) plus a `map_role_slug(slug) -> str | None` lookup, single consumer
(`app/services/manifest_ingest.py`) in this pass. The undecided `ING-08` wiring is carried forward
(see PLAN.md § 6).

### D-04: Email format validated via a lightweight in-repo regex, not `pydantic[email]`/`EmailStr` · blast:feature · rev:mechanical · adr:—

**Context**: research risk #6 suggested Pydantic's `EmailStr` for `team[].email`/alias validation.
`EmailStr` requires the `email-validator` package, which is not a dependency anywhere in
`services/api/pyproject.toml` today, and no other schema in this codebase validates email format
(this would be the first). Adding a new production dependency for one field's format check is a
larger footprint than the check needs, and would trip `plan-validation`'s config-drift dimension
for one cosmetic validation rule.

**Decision**: `app/schemas/manifest.py` validates `email` (primary and each `aliases[]` entry)
against a simple, permissive `local@domain` regex via a `field_validator`, no new dependency added.
See D-09 for how a validation failure is classified (row-level, not request-level).

### D-05: Two-tier validation is pre-write filtering, not per-row transactional rollback · blast:feature · rev:mechanical · adr:—

**Context**: `ING-10-FR-1` (Research Condition C-1, resolved) requires a `program:` schema/enum
failure to abort the whole request with zero writes, while a bad `team[]` role slug rejects only
that entry's rows and everything else still commits. A savepoint-per-row rollback strategy would
work but adds transactional complexity (nested `SAVEPOINT`/`ROLLBACK TO SAVEPOINT`) for a case that
doesn't need it: every input is fully knowable before any write is issued.

**Decision**: `manifest_ingest.py` validates the entire payload first — the `program:` block's
schema/enum, then every `team[]` entry's role slug and email format — and partitions `team[]` into
`valid_entries`/`rejected_entries` in memory. A `program:` failure returns `400` before any
DB statement is issued. Otherwise, only `valid_entries`' rows (expanded to primary + aliases) ever
reach the upsert statements; `rejected_entries` are never written, only reported. One commit per
request (the valid case), never a partial rollback.

### D-06: Roster upsert + soft-delete/un-delete via two batch statements in one request-scoped transaction · blast:feature · rev:mechanical · adr:—

**Context**: `.claude/rules/performance-baseline.md` forbids per-row queries/N+1 fan-out. A naive
per-team-member Python loop issuing one `SELECT` + conditional `INSERT`/`UPDATE` per row would cost
`O(team_size)` round-trips even after `ING-10-FR-5`'s 500-entry cap.

**Decision**: (1) one batch `postgresql.insert(ProgramRoster).values([...]).on_conflict_do_update(
index_elements=["program_id", "email"], set_={...})` covering every valid row (primary + alias
expansion) for the request's `program_id` — this both inserts new members and resets
`removed_at=NULL` for a reappearing email in the same statement; (2) one batch `UPDATE
program_roster SET removed_at = now() WHERE program_id = :pid AND email NOT IN (:present_emails)
AND removed_at IS NULL` for everyone the new payload no longer lists. Both statements, plus the
`program_summary`/`user_roles` upserts, run on the same `AsyncSession` and commit together once,
at the end of a successful request.

### D-07: Response `roster` detail is keyed per `team[]` entry (primary email), not per expanded row · blast:feature · rev:mechanical · adr:—

**Context**: `program-manifest-api`'s `response` field specifies "per-email created/updated/skipped
[and rejected] detail" but doesn't say whether "per-email" means per `team[]` entry or per
database row (primary + every alias are separate rows per D-01/ADR-0010). Reporting per-row would
mean the same person's aliases appear as separate, otherwise-identical response entries with no
added information for the caller (a `.harness/program.yaml` author who wrote one `team[]` entry
with 2 aliases).

**Decision**: `ManifestResponse.roster_detail` has exactly one entry per `team[]` array element,
keyed by that entry's primary `email`; a `created`/`updated`/`skipped`/`rejected` status and
optional `reason` describe the whole entry's outcome (primary + its aliases move together — they
share one role and one validation outcome by construction, per D-01).

### D-08: `program.type` and `team[].role` are typed as plain `str` in the request schema, not `Literal`/enum · blast:feature · rev:mechanical · adr:—

**Context**: `ING-10-FR-1` requires an out-of-enum `program.type` to return an explicit `400` with
this endpoint's own error envelope (`error_body("http_400", ...)`, matching `ingest-files-api`'s
precedent), and a bad `team[].role` slug to reject only that row with a reason — neither is
FastAPI's default `422 validation_error` shape. A Pydantic `Literal`/`Enum` field fails at model
construction time, before the handler body runs, and FastAPI converts that into
`RequestValidationError` → `422` for the *whole* request regardless of which field failed —
which is the wrong status code for `program.type` and the wrong granularity for `team[].role`
(one bad slug would 422 the entire payload, including every valid entry).

**Decision**: both fields stay plain `str` in `app/schemas/manifest.py`. `program.type`'s enum
membership check (`Greenfield|Brownfield|Upgradation|Migration|Maintenance`) and `team[].role`'s
slug-map lookup both run explicitly inside `manifest_ingest.py`, which raises `HTTPException(400,
...)` for the former and appends to `rejected_entries` for the latter (D-05).

### D-09: Malformed `team[]` email format is a row-level rejection, not a request-level abort · blast:feature · rev:mechanical · adr:—

**Context**: `ING-10-FR-1` names only `program:`-block schema/enum failures as request-level and
only a bad `role` slug as the row-level example — it is silent on a malformed `team[].email`.
Research risk #6's own suggested mitigation ("reject with 400 if format invalid, AC-5 whole-request
abort pattern") would contradict FR-1's stated principle that only the `program:` block causes a
whole-request abort, and would let one team member's typo invalidate every other valid entry in
the same push.

**Decision**: a malformed email (primary or any `aliases[]` entry, D-04's regex) is classified and
reported the same way as an unmapped role slug — that `team[]` entry's rows go to the roster
`rejected` bucket with a reason, while identity and every other valid entry still commit. This is
the reading consistent with FR-1's own request-vs-row split, not a new exception to it.

### D-10: `admin` roster slug maps to no persona (supersedes D-03's three-way executive fold) · blast:security · rev:mechanical · adr:—

**Context**: D-03 folded `cxo`, `board_member` and `admin` onto the `cio` persona. Code review raised
this as F-1 (MEDIUM, safety-security) and it was flagged as `AF-01`. `cio` bypasses program scoping
entirely — `/api/programs` returns every program for it — and a roster slug is whatever a program's
own committed `.harness/program.yaml` says, reviewed only by that program's PR reviewers. So the
mapping let a program grant org-wide dashboard visibility from inside its own repo. The Keycloak
path had already declined the same grant: when `config/persona_role_map.yaml` was populated in
PR #235, `admin: cio` was deliberately omitted, with the committed reasoning that "mapping a broad
IdP role such as `admin` to `cio` would hand org-wide visibility to that role, which is a decision
for whoever owns the realm."

**Decision**: triaged `accept` by the engineer on 2026-09-08. `admin` is removed from
`_ROLE_SLUG_TO_PERSONA`, so `map_role_slug("admin")` returns `None` and an `admin` roster entry
becomes a row-level rejection with a reason — fail-closed, granting nothing. `cxo` and
`board_member` keep folding onto `cio`: both are unambiguously executive titles, and persona-resolver's
vocabulary has only five values so some fold is unavoidable. The roster path now matches the
Keycloak path. `test_map_role_slug_admin_is_deliberately_unmapped_af01` asserts the absence, so
re-adding the mapping fails loudly rather than silently restoring the grant.

### D-11: `program_roster.role` stores the raw roster slug (amends the frozen `program-roster-schema` contract) · blast:data · rev:mechanical · adr:—

**Context**: `AF-13`. The Product-Gate-approved test case `ING-10-TC-01`, published as tracker issue
**#241**, asserts `program_roster.role == 'dev'`/`'arch'` — the raw slugs — while asserting
`user_roles.role == 'developer'` in the same breath. `DATA-DESIGN.md` and the frozen
`data.md#program-roster-schema` contract said the column held the long-form mapped role, and the
implementation followed the contract. Validation confirmed the code was correct and TC-01's text was
wrong. The two could not stay in disagreement: whichever source a reviewer trusted determined
whether they judged the implementation broken.

**Decision**: triaged `accept` by the engineer on 2026-09-08, choosing to change the code and
contract to match the published test case rather than correct the test case. `program_roster.role`
now stores the raw slug; `user_roles.role` still stores the long-form mapped value — the two columns
differ deliberately. `map_role_slug()` still runs during ingest, because a slug that maps to nothing
is a row-level rejection; its return value simply no longer lands in `program_roster`.

**Verified before accepting, not assumed**: `AUTH-06` is the sole consumer of
`program-roster-schema`, and its read pattern is
`SELECT DISTINCT program_id FROM program_roster WHERE email = :session_email AND removed_at IS NULL`
— it never selects `role`, so nothing has to translate on read. An earlier objection that AUTH-06
would need to re-translate was checked and found to be wrong. `data.md` gained an explicit
`role_semantics` field so this cannot drift silently again.

**Note on process**: this amends a contract *after* the Product Gate approved it, so the change is
recorded here rather than made quietly. `docs/test-cases/ING-10.json` and issue #241 are unchanged
and remain the authority the code now matches.
