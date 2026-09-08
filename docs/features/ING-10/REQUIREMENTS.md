# Feature: ING-10 — POST /api/ingest/manifest — program identity + team roster ingest

## Problem

Program membership today comes from the OIDC `groups` claim (`app/core/auth.py`'s `_parse_programs()`, prefix `PROGRAM_GROUP_PREFIX`): onboarding a new program requires creating a Keycloak group plus a Group Membership mapper — realm administration for what should be a reviewed file change. Separately, `program_summary.name/type/description` are read by `PGD-01`'s header and `AUTH-04`'s switcher `label`, but no story populates them — `BED-03`'s rebuild only carries forward whatever already exists (`a1a765a`), and nothing writes it in the first place.

## Outcome

A bearer-token-authenticated `POST /api/ingest/manifest` request, scoped to one program via `allowed_program_ids`, upserts that program's identity columns and team roster in a single call. `program_summary`'s header/switcher label populate from a reviewed `.harness/program.yaml`; the new `program_roster` table gives `AUTH-06` a membership source keyed by email (primary + every alias) that survives `ING-02`'s activity-triggered rollup rebuild untouched.

## Constraints

- Frozen contracts: `program-manifest-api`, `program-roster-schema` (produced — `docs/requirements/api.md` / `data.md`); `ingest-token-auth` (`ING-01`), `db-schema` (`BED-01`) (consumed) — shape, fields, and response keys are locked from this PRD forward for `AUTH-06` and any later consumer.
- `program_roster` is a **new, additive table** (#19), **not** `program_members`: `services/api/app/services/rollup_rebuild.py:360,370` unconditionally `delete(ProgramMembers)` and rebuilds it from `usage_events` with no prior-state carry-forward — a roster upsert into that table would be silently wiped by the next `ING-02` ingest. No validated story (`BED-03`) reopens; `db-schema`'s 18-table shape (`BED-01`) is unchanged.
- New Alembic revision chains after `002_personal_usage_indexes.py`.
- Wire format is the canonical two-file `.harness` layout only — committed `program.yaml` (`programId`, `program:`, `team[]`); local/gitignored `profile.yaml` is a self-check the dashboard never trusts (RTM Decisions 2026-09-08).
- `push_manifest` (MCP/CLI transport, `ING-04`/`ING-06`) is deliberately **deferred**; `program-manifest-api`'s `consumed_by` stays `[]` — a knowingly under-declared edge, not this story's scope to close (RTM Decisions 2026-09-08).
- No UI screen: `design_mode = none` — the `ING` epic has no entry in `docs/design/schema.json` → `designSystem.pages.features`. See `## Visual spec`.
- **Supersedes story AC-10's wording for `Upgradation`** (resolved during this PRD's authoring, 2026-09-08): AC-10 as validated states `Upgradation` "returns its own `{color, background}` pair rather than falling through to the `Migration` default," same treatment as `Greenfield`/`Brownfield`. That is now known-wrong: no approved token exists for `Upgradation` (`docs/design/tokens.md` § Program type colors has no row for it), and inventing one (`#0f9b8e`/`#e6f3f2`, the story's own Decision-log assumption) is exactly the silent-guess `clarification-marker`'s provenance rule forbids. `Upgradation` stays unmapped and deliberately falls through to `PROGRAM_TYPE_COLORS["Migration"]`. The story file is not re-edited (`Status: Validated`); this PRD is authoritative — see `ING-10-FR-6`.
- `.claude/rules/security-baseline.md`, `.claude/rules/performance-baseline.md`, `.claude/rules/reusability-baseline.md` bind on every new file this story touches.

## Solution sketch

A single `POST /api/ingest/manifest` endpoint, authenticated and program-scoped by the existing `ingest-token-auth` bearer dependency, accepts `{programId, program:{name,type,description}, team:[{email,name,role,aliases[]}]}`. The identity block upserts `program_summary`'s descriptive columns; the roster block upserts the new `program_roster` table with one row per team member's primary email plus every alias, mapping short role slugs to dashboard roles through a shared table, soft-deleting members a re-push no longer lists and un-deleting ones it lists again. A malformed `program:` block aborts the whole request with zero writes; a bad role slug on one `team[]` entry rejects only that entry while everything else commits. The response reports per-section received/valid/rejected counts and per-email created/updated/skipped detail.

## Addressing Research Conditions

- **C-1 (validation atomicity) — RESOLVED.** Two-tier validation, encoded in **ING-10-FR-1**: a `program:` schema/enum failure aborts the whole request (`400`, zero writes to `program_summary`/`program_roster`/`user_roles`); a `team[]` entry's role-slug failure rejects only that entry's rows (primary + aliases), while identity and every other valid entry commit. Settled on `program-manifest-api`'s already-frozen `response` field ("received/valid/rejected counts per section … plus per-email created/updated/skipped and rejection reasons" — meaningless under all-or-nothing), not the original faulty "one transaction" citation (grep-verified absent from `docs/prd/roster-sourced-program-membership.md`). See story Decision log 2026-09-08.

- **C-2 (PII logging) — mitigation specified.** **ING-10-FR-2** pins `ingest_manifest_write`'s exact field allowlist. `email`/`name` never appear — not in the structured fields, not interpolated into the message string. Enforcement is a unit test asserting the emitted record's full payload contains no PII field, mirroring `AUTH-03-FR-2`'s pattern (`test_persona_mapping_loaded_event_contains_no_pii_tc15`).

- **C-3 (`Upgradation` color) — RESOLVED, documented fallback, invent nothing.** **ING-10-FR-6**: `Greenfield`/`Brownfield` get short-name keys reusing the existing `Greenfield feature development`/`Brownfield feature development` hex pairs already in `docs/design/tokens.md` (`#1f8a5b`/`#e8f5ee`, `#7c5cff`/`#efebff`). `Upgradation` is deliberately left unmapped — falls through to `programStyle.ts`'s existing `?? PROGRAM_TYPE_COLORS["Migration"]` fallback — same treatment for the avatar-abbreviation column (`M`/`G`/`B`/`MT`), which also has no `Upgradation` entry. The gap is recorded, not silently closed — see Documentation requirements.

## Scope

**In:**
- `POST /api/ingest/manifest` route: auth + program-scope via `ingest-token-auth` (401/403), request parsing, response assembly.
- Identity upsert: `program:` → `program_summary.name/type/description`.
- Roster upsert: `team[]` (+ `aliases[]`) → new `program_roster` table, alias row expansion, soft-delete + un-delete on re-push (`ING-10-FR-4`).
- Role-slug → dashboard-role mapping table, in-process, `ING-10`-scoped (`ING-10-FR-3`).
- Two-tier validation split — request-level `400` vs. row-level rejection bucket (`ING-10-FR-1`).
- `413` cap at 500 raw `team[]` entries pre-alias-expansion (`ING-10-FR-5`).
- `programStyle.ts` `PROGRAM_TYPE_COLORS` widening — `Greenfield`/`Brownfield` short-name keys only (`ING-10-FR-6`).
- Locking `program-manifest-api` and `program-roster-schema` contract shape for `AUTH-06`.

**Out:**
- `push_manifest` MCP tool / CLI transport (`ING-04`/`ING-06`) — deferred, RTM Decisions 2026-09-08.
- This repo's own `.harness/profile.yaml` migration to the canonical two-file layout — carried forward, touches `ING-06`'s dogfooding path.
- `program_members` enrichment with roster name/role — real follow-on, not asked for by the PRD's Functional Expectations, carried forward for `PGD-05`.
- Wiring `ING-08`'s Keycloak role-sync onto the shared role-map table — undecided scope change to an already-shipped story.
- `Upgradation` color/avatar-abbreviation token invention — deliberately left unmapped pending a real design decision (C-3).
- `session.programs` derivation from `program_roster` — that read path is `AUTH-06`'s scope; this story only writes the table.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/ING-10.md` for canonical wording. New impl constraints introduced below:

**ING-10-FR-1** — Two-tier validation atomicity *(Research Condition C-1; extends AC-5/AC-6 with the exact partition)*

A `program:` block failing schema/enum validation (`type` not one of `Greenfield|Brownfield|Upgradation|Migration|Maintenance`) aborts the entire request: `400`, zero rows written to `program_summary`, `program_roster`, or `user_roles`. A `team[]` entry whose `role` is not one of the mapped slugs is rejected at row granularity: that entry's rows (primary email + every alias) go into the roster `rejected` bucket with a reason; the identity write and every other valid `team[]` entry in the same request still commit. No single database transaction wraps the whole payload — only the failing entry's rows are excluded from the commit set.

**ING-10-FR-2** — `ingest_manifest_write` log-event field allowlist *(Research Condition C-2; extends the story's Observability NFR with an exact, enforced field set)*

| Field set | Fields |
|---|---|
| Required | `{program_id, token_label, identity_written, roster_received, roster_valid, roster_created, roster_updated, roster_removed, roster_rejected, duration_ms}` |
| Optional | `{}` |

`email` and `name` are never included — not as structured fields, not interpolated into the log message string. A unit test asserts the full emitted record (message + fields) contains no PII, pattern: `AUTH-03-FR-2` / `test_persona_mapping_loaded_event_contains_no_pii_tc15`.

**ING-10-FR-3** — Role-slug mapping table *(extends AC-3/AC-6 with the exact map)*

`dev→developer, arch→architect, pm→product-manager, em→engineering-manager, cxo→cio, board_member→cio` (story Decision log 2026-09-08). `admin` is deliberately UNMAPPED — removed 2026-09-08 per DECISIONS.md D-10 / flag AF-01 because folding it onto `cio` granted org-wide visibility from a program-owned file; it now returns None and is rejected row-level. In-process module-level table (`app/core/role_map.py`), single consumer (`ING-10` itself) in this pass; wiring `ING-08` onto it is an undecided scope change and out of scope here.

**ING-10-FR-4** — Roster row expansion, upsert key, and soft-delete/un-delete *(extends AC-4/AC-7 with the exact row and removal semantics)*

One `program_roster` row per primary email plus every `aliases[]` entry, sharing `name`/`role`; upsert key `unique(program_id, email)`. A full manifest re-push sets `removed_at = now()` on any existing row for that `program_id` whose email is no longer present in the new `team[]`/`aliases[]` payload; a later re-push whose payload lists that email again resets `removed_at` to `null`. Invariant: every membership read (including `AUTH-06`'s `session.programs` derivation) filters `WHERE removed_at IS NULL` — this story owns the write side of that invariant, not the read.

**ING-10-FR-5** — Payload size cap *(extends AC-8 with the exact threshold and enforcement point)*

`team[]` raw entry count, counted **before** alias expansion, greater than 500 → `413` returned before any row is parsed or written.

**ING-10-FR-6** — `PROGRAM_TYPE_COLORS` widening, deliberately partial *(Research Condition C-3; supersedes AC-10's "each returns its own pair" wording for `Upgradation`)*

`apps/web/src/lib/programStyle.ts`'s `PROGRAM_TYPE_COLORS` gains two short-name keys reusing existing hex pairs: `Greenfield` → `{color: "#1f8a5b", background: "#e8f5ee"}` (same pair as `"Greenfield feature development"`); `Brownfield` → `{color: "#7c5cff", background: "#efebff"}` (same pair as `"Brownfield feature development"`). The 4 existing long-name keys are kept, not replaced. `Upgradation` is **not** added — it falls through to the existing `?? PROGRAM_TYPE_COLORS["Migration"]` fallback (`getProgramStyle()`'s current behavior, unchanged). Same treatment applies to `docs/design/tokens.md` § Program type colors' avatar-abbreviation column (`M`/`G`/`B`/`MT`): add abbreviations for the two new short-name keys (`G`, `B` — same letters as the existing long-name rows), leave `Upgradation` absent.

**ING-10-FR-7** — Response shape *(extends AC-3 with the exact contract fields)*

Per `program-manifest-api`'s frozen `response` field: received/valid/rejected counts for each of the `identity` and `roster` sections, plus per-email `created`/`updated`/`skipped` detail and rejection reasons for the roster section.

## Non-functional requirements

- Performance: Per `.claude/rules/performance-baseline.md`: applies to the new `POST /api/ingest/manifest` handler and its service layer. Batch upsert only, bounded by `ING-10-FR-5`'s 500-entry cap — no per-row queries, no unbounded fan-out. Not a list endpoint (write-only), so the rule's pagination clause does not apply; the size cap is this endpoint's equivalent bound on untrusted input. Feature-specific budget: p95 < 500ms for a manifest up to the AC-8 cap (story Decision log 2026-09-08, assumption — positioned between `ING-03`'s <300ms and `ING-02`'s <3s, since this endpoint does a bounded upsert with no rollup rebuild of its own).
- Security: Per `.claude/rules/security-baseline.md`: applies to `POST /api/ingest/manifest` and the manifest-ingest service — untrusted input at a trust boundary, schema/enum-validated before any write (`ING-10-FR-1`), PII (`email`/`name`) never logged (`ING-10-FR-2`).
- Accessibility: N/A — backend endpoint; `ING-10-FR-6`'s `programStyle.ts` change is a color-token lookup with no independent UI surface in this story.
- Observability: `ingest_manifest_write` structured JSON log event (`ING-10-FR-2`) — extends the `ingest_write_completed`/`ingest_artifacts_write` naming precedent (`ING-02`/`ING-03`).

## Visual spec

Not applicable — `integrations.design = html-mockup`, but the `ING` epic has no entry in `docs/design/schema.json` § `designSystem.pages.features`. Backend ingest endpoint; `ING-10-FR-6`'s `programStyle.ts` widening is a token-lookup change with no independent screen.

## Rollout plan

- **Strategy**: bang-bang. New endpoint, new additive table, no existing route's behavior changes; `AUTH-06` (the only reader of `program_roster`) is a separate, not-yet-planned story.
- **Feature flag**: none.
- **Backout plan**: revert the PR. `program_roster` is additive (down-migration drops an unread table); `program_summary`'s identity columns already exist (`BED-01`) and simply stop being upserted.
- **Success signal**: a manifest `POST` with a real ingest token returns `200` with correct per-section counts, `program_summary` reflects `program:`, and `program_roster` holds primary + alias rows queryable by `AUTH-06` with no further migration.

## Documentation requirements

- **README updates**: `services/api/README.md` — add `POST /api/ingest/manifest` to the API table (existing `/auth/*`-table style): auth (`ingest-token-auth` bearer), request/response shape, `400`/`401`/`403`/`413` codes.
- **Runbook**: none — no new operational lever beyond `ING-01`'s existing token-minting script.
- **API reference**: `docs/requirements/api.md` § `program-manifest-api` / `docs/requirements/data.md` § `program-roster-schema` are the frozen machine-readable contracts; FastAPI `/docs` covers the rest.
- **Inline code comments**: module docstring on the manifest-ingest service covering (a) the two-tier validation split (`ING-10-FR-1`) and (b) why `program_roster` is a separate table from `program_members`, not a "fix" to unify them (RTM Decisions 2026-09-08) — pattern: `ING-01`'s auth-module docstring precedent for a deliberate, non-obvious design choice.
- **Examples / how-to**: `docs/design/tokens.md` § Program type colors — add the two short-name key rows (`Greenfield`, `Brownfield`) pointing at their existing hex pairs, and record `Upgradation` (color + avatar abbreviation) as an explicit open gap awaiting a real design token, not an invented one (`ING-10-FR-6`).

## Open questions

<!-- None open. needs_clarification_count: 0. docs/research/ING-10.md § Open Clarifications  -->
<!-- reads "RESOLVED — none open." All three GO-WITH-CONDITIONS items (C-1, C-2, C-3) are     -->
<!-- addressed above with concrete mitigations. No new ambiguity surfaced during drafting.     -->
<!-- Decisions logged in docs/stories/ING-10.md § Decision log.                                -->
<!--                                                                                            -->
<!-- Kept as a comment deliberately, matching ING-01: the phase-preconditions clarification    -->
<!-- gate treats any non-blank, non-comment line in this section as an unresolved open question -->
<!-- and aborts the next phase.                                                                -->

## Approvals

| Role | Reviewer | Date | Verdict |
|---|---|---|---|
| Product Owner | Pratik Pawar | 2026-09-08 | APPROVE |
| Designer | — | 2026-09-08 | N/A — backend-only story; `ING` has no epic in `docs/design/schema.json`, so `design: n/a` per `CLAUDE.md` |
| BA | Pratik Pawar | 2026-09-08 | APPROVE, with the coverage gap below accepted deliberately |

**Accepted deviation — test-case coverage.** Gate check "coverage audit shows zero uncovered ids"
does **not** pass, and was approved anyway as an explicit decision. Test-case generation was capped
at 2 cases by instruction, against 10 ACs and 7 FRs, so the following are uncovered:
`ING-10-AC-1`, `AC-2` (ingest-token 401/403), `AC-7` (soft-delete and un-delete on re-push),
`AC-8` + `FR-5` (413 oversized-payload cap), `AC-9` (BED-03 rollup identity carry-forward),
`AC-10` + `FR-6` (`programStyle.ts` colour map), `NFR-performance` (p95 < 500ms).

The two cases that exist cover the core mechanism end-to-end (`ING-10-TC-01`) and both
HIGH-severity research risks — two-tier validation and PII-in-logs (`ING-10-TC-02`) — so risk
coverage is sound while breadth is not. `AC-9` is the notable residual: it guards the BED-03
rollup interaction that would otherwise silently wipe roster identity (the defect decomposition
caught and PR #235 fixed), and it now ships unguarded by a test.

`/arh-implement` and `/arh-validate-feature` must treat this list as known-untested rather than
as passing.

