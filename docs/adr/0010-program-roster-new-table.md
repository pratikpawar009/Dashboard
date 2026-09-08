# ADR-0010: `program_roster` is a new, additive table — file-authoritative program membership, kept separate from `program_members`

- Status: Accepted
- Date: 2026-09-08
- Deciders: Pratik Pawar (Product Owner), ING-10 planning (via impl-planning-agent, `/arh-plan-implementation ING-10`)

## Context

Program membership today comes from the OIDC `groups` claim (`app/core/auth.py`'s
`_parse_programs()`): onboarding a new program requires creating a Keycloak group plus a Group
Membership mapper — realm administration for what should be a reviewed file change. Separately,
`program_summary.name/type/description` are read by `PGD-01`'s header and `AUTH-04`'s switcher
`label`, but no story populates them from a durable, program-owned source.

`ING-10`'s manifest endpoint needs a durable store for the roster a `.harness/program.yaml` push
carries. The obvious candidate — `program_members` (BED-01, `db-schema`) — is disqualified by a
code-verified defect risk, not a preference: `services/api/app/services/rollup_rebuild.py:360`
unconditionally `delete(ProgramMembers)`, and `:370` rebuilds it from `usage_events` with **no
prior-state carry-forward parameter** (unlike `program_summary`, which already has a
`prior_identity` seam letting identity survive a rebuild). A roster upsert into `program_members`
would be silently wiped by the very next `ING-02`-triggered activity ingest. `BED-01`'s validated,
shipped 18-table shape is not reopened by this decision.

## Decision

Add `program_roster` as a new Postgres table (table #19, `docs/requirements/data.md#program-roster-schema`)
via its own additive Alembic revision (`003_program_roster.py`) on top of `002_personal_usage_indexes`.
Fields: `id, program_id, email, name, role, source='file', removed_at (nullable), created_at,
updated_at`; `unique(program_id, email)` is the upsert key. One row per team member's primary
email **plus every `aliases[]` entry**, sharing `name`/`role` — matching how `usage_events.user`
carries whatever `git config user.email` a machine was set to. Removal is a soft-delete
(`removed_at = now()` on a re-push that no longer lists an email); a later re-push listing that
email again resets `removed_at` to `null`. An `index(email)` is added alongside the
`unique(program_id, email)` constraint — the latter's leading column is `program_id`, but
`program-roster-schema`'s own documented `read_pattern` for `AUTH-06` (`SELECT DISTINCT program_id
FROM program_roster WHERE email = :session_email AND removed_at IS NULL`) is email-first; adding
this index while this story already owns the table's DDL is cheaper than a second migration later.

`program_members` (BED-01, rollup) stays owned single-writer by `rebuild_program_rollups()`'s
full delete+rebuild cycle and is untouched by this story — no validated story reopens it.
`program_roster` becomes `AUTH-06`'s sole membership-read source (a separate, not-yet-planned
story), replacing the OIDC `groups`-claim derivation for that purpose. File is authoritative for
program membership going forward — the opposite precedence of the prior-art `file-roles.ts`
pattern, where Keycloak won and the file only filled gaps.

## Consequences

- Positive: onboarding a program's membership no longer requires Keycloak group administration —
  a reviewed `program.yaml` PR suffices. `rollup_rebuild()`'s existing single-writer invariant over
  `program_members` stays intact; this decision adds a table rather than risking BED-03's shipped,
  validated rebuild logic.
- Negative: two tables now answer "who is on a program" — `program_members` (usage-derived,
  read by `PGD-05`'s team panel) and `program_roster` (file-derived, read by `AUTH-06`) — with no
  automatic reconciliation between them. `program_members` rows stay unenriched with roster
  name/role until a follow-on story (carried forward, out of `ING-10`'s scope). A future reader
  must know which table answers which question.
- Reversible? Effectively irreversible once real programs push manifests: dropping the table loses
  membership history with no other durable source of truth, since the OIDC-groups path is being
  deliberately phased out as this data's source of record. Reverting means re-deriving membership
  from Keycloak groups again — the exact administrative overhead this decision exists to remove.
