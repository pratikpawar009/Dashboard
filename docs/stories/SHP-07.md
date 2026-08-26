# Story: SHP-07 — Extended role/team taxonomy beyond 4 roles

**Epic**: SHP
**Status**: Validated
**Priority**: P3
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#35 (https://github.com/pratikpawar009/Dashboard/issues/35)

## User story

As a platform engineer, I want an explicit, reversible Alembic migration path for adding a
role beyond the current fixed 4 (Developer/Architect/Product Manager/Engineering Manager) so
that when a finer role taxonomy is required (e.g. QA), MAU-by-role and team-role reporting can
extend to include it without a schema rewrite (FR-SH-22, R-005).

## Acceptance criteria

1. Given a new role needs to be added to the taxonomy (e.g. `qa`, per FR-SH-22/R-005), when
   the Alembic migration for it is authored and applied, then it adds a new nullable,
   zero-defaulted column to `mau_series` for that role and extends the `program_members.role`
   domain to accept the new value, leaving the existing `developer`/`architect`/
   `product_manager`/`engineering_manager` columns and their historical data unchanged
   (FR-SH-22, R-005).
2. Given the migration has been applied, when `GET /api/overview/mau-series` (OVW-03,
   `overview-mau-series-api` contract) is called, then each of the 12 monthly points includes
   the new role's key alongside the 4 existing keys, zero-padded for any month with no rows
   for that role — consistent with OVW-03 AC1's zero-padding rule.
3. Given the migration has been applied, when `program-team-api` (PGD-05) returns a program's
   team rows, then a member assigned the new role has that value in their `role` field rather
   than being coerced into one of the original 4 roles (FR-SH-22, `program-team-api`
   contract).
4. Given the migration, when `alembic downgrade` is run for it, then the schema cleanly
   reverts to the prior 4-role shape with no data loss to the original 4 role columns
   (mirrors BED-01 AC2's reversibility requirement — same migration mechanism).
5. Given an existing OVW-03 chart / PGD-05 table consumer that is not yet role-taxonomy-aware,
   when it reads the extended `mau-series` / `program-team-api` responses, then the additional
   role key/value is an additive field only — the 4 pre-existing keys/values are unchanged, so
   no breaking change is introduced for unmodified consumers (FR-SH-22 "additional role
   segments appear" — additive, not a replacement).

## Non-functional requirements

- Performance: N/A — schema/migration plus an additive API field only; OVW-03's existing p95
  < 300ms and PGD-05's ≤ 2s range-refresh budgets are unaffected by one extra column —
  assumption, PRD gives no separate budget for this extension.
- Security: no new security surface — the existing `org_access` check gating `mau-series`
  (AUTH-03, via OVW-03) and `program_visibility` check gating `program-team-api` (AUTH-03, via
  PGD-05) continue to apply unchanged to the extended response (sourced: rbac-checks contract
  scope is untouched by an additive column).
- Accessibility: N/A — backend schema + API-field story only; FR-SH-22's own file-path column
  (`backend/alembic/versions/`) scopes this work to backend (sourced, FR-SH-22). Rendering the
  new role segment in OVW-03's stacked chart or PGD-05's team table is a follow-on UI concern,
  out of this story's scope.
- Observability: migration failures surfaced via Alembic's `alembic_version` table plus
  structlog JSON on failure, consistent with BED-01's precedent for schema-migration
  observability — assumption, NFR-011 does not name a role-taxonomy-specific event.

## Dependencies

- Upstream: BED-01 via `db-schema` contract (`docs/requirements/data.md`) — extends the
  `mau_series`/`program_members` tables it defines; OVW-03 via `overview-mau-series-api`
  contract (`docs/requirements/api.md`) — extends the MAU-series endpoint's fixed 4-column
  response; PGD-05 via `program-team-api` contract (`docs/requirements/api.md`) — extends the
  team table's `role` field domain.
- Downstream: none — no story lists SHP-07 in `Depends-on`, and neither contract this story
  touches lists a further consumer of SHP-07 itself.

## Test mapping

- E2E: NA — no dedicated E2E flow file yet; backend-only schema/API extension.
- Unit: `backend/tests/test_migrations.py` (new-role migration upgrade/downgrade round-trip),
  `backend/app/services/overview.py` and `backend/app/services/program_detail.py`
  (new-role-key presence in `mau-series` / `program-team-api` responses).
- Manual: NA

## Clarifications

## Decision log

- 2026-08-26 Example role used in ACs: `qa` — per FR-SH-22/R-005's own example ("e.g. QA"),
  used illustratively; the story is not scoped to any one specific role name.
- 2026-08-26 New `mau_series` column nullability/default: nullable, zero-defaulted — assumption,
  consistent with OVW-03's zero-padding behavior for months with no data; source does not state
  a column-level default.
- 2026-08-26 Migration reversibility (AC4): required, mirroring BED-01's downgrade precedent —
  assumption, not restated in FR-SH-22 itself but standard practice already established for
  this schema's migration chain.
- 2026-08-26 Frontend rendering of the new role segment: out of scope for this story —
  assumption, based on FR-SH-22's file-path column naming only `backend/alembic/versions/` and
  this story's contract list (`db-schema`, `overview-mau-series-api`, `program-team-api`) being
  backend-only, with no UI contract listed as produced or extended.
- 2026-08-26 Backward-compatibility requirement for existing consumers (AC5): additive-only
  response change — assumption, inferred from FR-SH-22's phrasing ("additional role segments
  appear"), not an explicit compatibility clause in the source.
- 2026-08-26 Migration-failure observability: tracked via Alembic's `alembic_version` table
  plus structlog JSON on failure — assumption, mirroring BED-01's precedent; NFR-011 mandates
  structlog JSON output generally but names no role-taxonomy-specific event.
