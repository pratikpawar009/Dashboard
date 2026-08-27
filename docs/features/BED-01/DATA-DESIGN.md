# BED-01 — Data Design

State & data management for the 18-table `db-schema` contract (Postgres, SQLAlchemy 2.0 + Alembic). Field-level detail below mirrors the authoritative contract this story produces, `docs/requirements/data.md#db-schema` — that file is the single source of truth for downstream stories; this section exists so migration/consistency/performance design (§§2,5,8) has the shape in front of it.

## 1. Data model

18 tables, 3 groups, all Postgres tables via one `Base` (SQLAlchemy 2.0 `DeclarativeBase`, DECISIONS.md D-01). Every table has a `String` `id` primary key (app-generated `uuid4().hex`) except `system_metadata` (`key` PK), `persona_config` (`role` PK), `user_roles` (`email` PK) — PRD §8.4 names those 3 as natural-key tables.

### Rollups (10 tables — read path, rebuilt on every ingest write)

| Table | Key fields | Class | Notes |
|---|---|---|---|
| `org_summary_rollup` | `org_id` unique (singleton, default `"org-1"`) | Internal | Counts (Integer) + `total_token_consumption`/`lines_of_code_generated` (BigInteger) |
| `token_series` | unique `(org_id, month)` | Internal | `value` BigInteger |
| `mau_series` | unique `(org_id, month)` | Internal | 4 fixed role columns (developer/architect/product_manager/engineering_manager) — adding a 5th role is a new migration, not config (PRD R-005) |
| `program_summary` | `program_id` unique | Internal | `monthly_token_sparkline` JSONB; `intervention_count`/`tool_rejections` nullable |
| `program_releases` | index `program_id` | Internal | `type` plain String (`major\|minor\|patch`), no Postgres enum |
| `program_commands` | index `program_id` | Internal | — |
| `program_members` | index `program_id` | Confidential (individual) | `user_id`, `name` — per-member rollup |
| `session_series` | unique `(org_id, program_id, member_id, date)` | Confidential (individual) | `member_id` nullable = org/program-wide row |
| `program_token_series` | unique `(program_id, date)` | Internal | 4 token-breakdown Integer columns default 0 |
| `user_sessions` | unique `session_identifier` | Confidential (individual) | `user_id`, `duration_seconds`, `tokens` BigInteger |

### Governance (3 tables — static reference data)

| Table | Key fields | Class | Notes |
|---|---|---|---|
| `program_artifacts` | unique `(program_id, type)` | Internal | `type` ∈ prd\|user_story\|test_case\|arch_diagram\|api_spec, plain String |
| `program_guardrails` | unique `(program_id, name)` | Internal | `status` ∈ Enforced\|Warning\|NotImplemented, plain String |
| `org_constitution` | unique `(org_id, category)` | Internal | `document_ref` links to an external governance document |

### Ingestion / auth / system (5 tables)

| Table | Key fields | Class | Notes |
|---|---|---|---|
| `usage_events` | unique `(program_id, session_id, cmd_ts)`; index `(program_id, ts)`, `(program_id, user)`, `(program_id, command)`, `(program_id, session_id)` | Confidential (individual activity) | Source of truth every rollup above is rebuilt from (A-002); retention/archival out of scope for BED-01 (documented inline, PRD R-001/NFR-014) |
| `ingest_tokens` | unique `token_hash`; index `user_email` | Sensitive (`token_hash` = hashed credential) / PII (`user_email`) | No column can hold a raw token (AC-5, NFR-006) — enforced by BED-01-TC-10/TC-18 |
| `system_metadata` | `key` PK | Internal | Drives freshness timestamp shown to all personas |
| `persona_config` | `role` PK | Internal | Lowest-precedence tier of the 3-tier RBAC resolver (FR-AUTH-03, AUTH-02/04 build on this) |
| `user_roles` | `email` PK | PII (`email`) | Reference/audit only — populated by a role-sync CLI (ING stories), not read at session time |

## 2. Migrations

Single hand-written Alembic revision, `migrations/versions/001_initial_schema.py` — no autogenerate (research: `target_metadata = None` today, `--autogenerate` has nothing to diff until models exist). `upgrade()` creates all 18 tables via `op.create_table(...)` + `op.create_index(...)`; `downgrade()` drops them in reverse dependency order (no FKs between these tables — every relationship is a soft `*_id String` reference, not a `ForeignKey`, matching the reference Prisma schema's own choice — so `downgrade()` can drop in any order). Zero-downtime is N/A: this is the first-ever migration against an empty database (Rollout plan: bang-bang, no live traffic). **Forward + backward** — both directions are required and tested (AC-2, `BED-01-TC-04`/`TC-05`). Per FR-2 / C-2 (PRD spec lock): once merged, `001_initial_schema.py` is never edited — any correction is a new revision (enforced by code review + the module's own docstring, `BED-01-TC-17`).

## 3. Ownership & tenancy

Single-org deployment for this story (no `org_id` FK/tenant column beyond the literal string default `"org-1"` on `org_summary_rollup`/`token_series`/`mau_series` — resolved in research, confirmed by user 2026-08-26). No server-side ownership-guard enforcement is built in this story — RBAC/program-membership scoping is explicitly out of scope here (AUTH-02/04 own it) and no request-serving route reads these models yet (`app/api/*` still carry `TODO(implementation)` markers). This story only owns the schema; the `.claude/rules/security-baseline.md` `_load_owned` guard applies to the routers AUTH-02/04/BED-02..04 build on top of these tables, not to this story's deliverable.

## 4. Data classification & retention

Per PRD §9.2 (reproduced in the per-table Class column above): individual-level tables (`usage_events`, `user_sessions`, `program_members`, `session_series`) are Confidential; program/org aggregates are Internal; `ingest_tokens.token_hash` is Confidential credential material (hashed, never raw — AC-5). Encryption at rest/in transit: "Expected — standard org practice" per PRD §9.2, no story-specific mechanism (Postgres-level, outside this story's scope). Retention: `usage_events` is explicitly unbounded in this story (PRD R-001, NFR-014 gap) — a comment in `app/models/ingestion.py` documents this is a known, accepted gap, not an oversight; carried forward to `state.json` `pending_carry_forward` (see PLAN.md §6).

## 5. Consistency & concurrency

Transaction boundary: one Postgres transaction per Alembic migration step, via `context.begin_transaction()` (`migrations/env.py:53,60`, unchanged by this story). Idempotency: `usage_events` unique on `(program_id, session_id, cmd_ts)` is the DB-level idempotency key duplicate ingest writes hit (AC-4) — this is a foundation for BED-03's rollup-rebuild invariant (A-002: `usage_events` is append/upsert-only; every rollup table is fully re-derived from it on each successful write, never incremental). Concurrent writes to the same `(program_id, session_id, cmd_ts)` are serialized by the unique-constraint conflict itself (second writer gets `IntegrityError`, per `BED-01-TC-08`) — no explicit row lock needed since this story defines schema only, not the ingest write path (ING-01/02/03). No distributed/multi-store concerns — single Postgres instance, no replicas or offline clients in scope.

## 6. Caching

N/A — no cache layer exists (ADR-0002: "No cache layer yet — add one only when a measured need appears"). This story adds no cache-invalidation surface.

## 7. Ephemeral / session state

N/A — this story has no request-serving code path (no routers touch these models yet) and no client/browser surface (`integrations.design = none`).

## 8. Query-path & access-path performance

`usage_events` carries 4 composite indexes (`(program_id, ts)`, `(program_id, user)`, `(program_id, command)`, `(program_id, session_id)`) matching the query patterns downstream dashboard/read stories (OVW/PGD/SHP) will need — declared now so BED-03's rollup-rebuild and later read APIs don't table-scan a table PRD R-001 already flags as unbounded-growth risk. No N+1 concern in this story (no queries are written here, only DDL). Pagination is N/A per this story's NFR section (no list endpoints in scope) — the reserved `page`/`page_size` pattern in `app/api/activities.py:11-18` is the convention the future read APIs (BED-02/04) must follow against these same tables.

## 9. Contract (API / interface)

Contract: `db-schema` → `docs/requirements/data.md#db-schema` (produced by this story, consumed by 13 downstream stories — concrete shape lives there, not duplicated here per plan-authoring). No HTTP/RPC contract in this story — no routers are added or modified.

## 10. Async & messaging

N/A — purely synchronous DDL applied once via `alembic upgrade head`; no message broker, queue, or scheduled job in this story's scope.
