# Requirement: roster-sourced program membership and program-manifest ingest

Source of this requirement: product decision confirmed 2026-09-08, recorded in
`docs/requirements/RTM.md` § Decisions (entries dated 2026-09-08). This file is the
decomposition input for `/arh-intake`.

## Problem

Program membership is currently derived from the OIDC `groups` claim: `app/core/auth.py`'s
`_parse_programs()` reads every `groups` entry prefixed with `PROGRAM_GROUP_PREFIX` (default
`program-`) and that list becomes `session.programs`, which `GET /api/programs` scopes on.

Two consequences make this the wrong source:

1. **Onboarding a program requires Keycloak changes.** Every new program needs a
   `program-<slug>` group created in the realm, plus a `groups` client scope carrying a Group
   Membership mapper. Program onboarding should not require realm administration.
2. **Nothing owns program identity.** `program_summary.name`, `icon`, `type` and `description`
   are read by PGD-01's Program Detail header and used as AUTH-04's switcher `label`, but no
   story populates them. BED-03's rollup rebuild actively defaults them to `""` (its decision
   D-03), which blanks both surfaces.

## Decision (already made — do not re-litigate)

Keycloak/OIDC is for **dashboard login only**: authenticating the user and resolving their own
dashboard persona. Per-program membership and per-program roles come from each monitored
program's own committed `.harness/program.yaml`, pushed to the dashboard.

This supersedes AUTH-04's 2026-08-26 decision that `session.groups` is "the sole source of
truth, no separate membership table".

It does **not** reverse the 2026-08-26 open-aggregate RBAC decision. Only the *source* of the
program list moves. `program_visibility` stays a veto gate passing for any authenticated
session; `GET /api/overview/program-detail/{program_id}` stays unscoped and byte-identical
across personas; `individual_usage_visibility` and `governance_visibility` stay the real
gates. `rbac-checks` and its 16 consumers need no change.

## The manifest

A real example is `/Users/pratik.pawar/Downloads/CIO Dashboard Project/.harness/program.yaml`.
It is committed and PR-reviewed on purpose — its own comment states roles live there "so nobody
can promote themselves", i.e. changing a role requires a reviewed commit. It carries:

- `programId`.
- `program:` — `name`, `type`, `description`. The authoritative source of the identity columns
  PGD-01 and AUTH-04 render.
- `team[]` — one entry per person: `email`, `name`, `role`, and `aliases[]` of other git
  identities the same human commits under.
- `files[]` and `artifacts{}` — already covered by ING-02 and ING-03; **out of scope here**.

A sibling `.harness/profile.yaml` is local-only and gitignored in that layout, and its `role`
is a self-check the dashboard must not trust.

## Functional expectations

1. **Manifest ingest endpoint.** `POST /api/ingest/manifest`, authenticated by the existing
   `ingest-token-auth` bearer token, with the same `allowed_program_ids` scope check ING-02 and
   ING-03 apply. Accepts the `programId`, `program:` and `team[]` sections.
2. **Identity write.** `program:` upserts `program_summary`'s four descriptive columns. These
   must survive a subsequent `rebuild_program_rollups()` (already true as of `a1a765a`, which
   made the rebuild carry them forward instead of blanking them).
3. **Roster write.** `team[]` upserts `program_members` for membership, and `user_roles`
   (`email` PK, `role`, `source="file"`) for the org-level role. **Every alias gets its own
   row** — usage joins on `usage_events.user`, which carries whatever `git config user.email`
   was set to on the producing machine, so a developer committing under a personal address is
   otherwise silently unattributed.
4. **Role mapping.** The roster's short slugs (`dev`, `arch`, `pm`, `em`, `cxo`,
   `board_member`, `admin`) map to the long dashboard roles through a single shared table, so
   the file writer and ING-08's Keycloak writer cannot drift apart.
5. **Membership becomes the scoping source.** `session.programs` is derived from
   `program_members` — matching the session's `email` against each roster entry's primary
   address *and* every alias — instead of the `groups` claim. `PROGRAM_GROUP_PREFIX`, the
   `groups` entry in `OIDC_SCOPE`, and the Keycloak `groups` client scope + Group Membership
   mapper documented in `README.md` are all retired.
6. **Program type vocabulary.** The manifest enum
   (`Greenfield|Brownfield|Upgradation|Migration|Maintenance`) is authoritative.
   `apps/web/src/lib/programStyle.ts`'s `PROGRAM_TYPE_COLORS` currently keys only `Migration`,
   `Greenfield feature development`, `Brownfield feature development` and `Maintenance`, so
   `Greenfield` and `Brownfield` fall through to the `Migration` fallback colour and
   `Upgradation` has none. Widen the map to cover the enum.
7. **`user_roles` stays off the session path.** ING-08's AC-4 ("`user_roles` is never read on
   the session path, reference/audit only") is unchanged. Program membership is read from
   `program_members`.

## Explicitly out of scope

- Activity-row ingest (`ING-02`) and artifact-count ingest (`ING-03`) — unchanged.
- Keycloak authentication itself: PKCE, JWKS validation, refresh, dev-bypass, persona
  resolution. Login is untouched.
- Retiring ING-08's Keycloak role-sync CLI. It is already reference/audit only and stays.
- Any change to `rbac-checks` or the open-aggregate model.

## Prior art to reuse, not reinvent

`/Users/pratik.pawar/Downloads/CIO Dashboard Project/src/lib/identity/file-roles.ts` implements
roster → `user_roles` with alias expansion and `source: "file"` tagging against the same shared
role-map table. Read it before designing a replacement.

Its precedence rule is the **opposite** of what is wanted here: there, Keycloak wins and the
file only fills gaps. Under this requirement the file is authoritative for program membership
and roles.

## Open questions for decomposition to resolve

1. **Transport surface for the MCP path.** `ING-04` exposes `push_activity` and
   `push_artifacts`. Does it also gain a `push_manifest` tool, and does `ING-06`'s manual CLI
   ingester push the manifest too? Adding either is a scope change to an already-validated
   story. Until settled, `program-manifest-api` has a single consumer, which this project's own
   traceability schema flags as a likely under-declared edge.
2. **This repo's own `.harness` layout.** `ING-06` makes this repo a self-monitored program,
   but its committed `.harness/profile.yaml` holds `files[]`/`artifacts{}` with no `program:`
   block and no `team[]` — while the reference layout puts those in a committed `program.yaml`
   and keeps `profile.yaml` local and gitignored. Two incompatible layouts are in play; one has
   to be chosen, and this repo's file migrated to it.
3. **Roster removal semantics.** When a person is deleted from `team[]` and the manifest is
   re-pushed, is their `program_members` row removed (losing their historical attribution in
   the team table), or retained and marked inactive? `usage_events` rows attributed to them
   are not deleted either way.
