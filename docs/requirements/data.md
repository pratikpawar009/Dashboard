### db-schema

```yaml
produced_by: BED-01
consumed_by: [BED-02, BED-03, BED-04, AUTH-02, AUTH-04, OVW-01, OVW-02, OVW-03, OVW-04, PGD-01, PGD-02, PGD-03, PGD-04, PGD-05, PGD-06, SHP-02, SHP-03, SHP-04, SHP-05, SHP-06, SHP-07, ING-01, ING-02, ING-03, ING-07, ING-08]
shape:
  mechanism: "SQLAlchemy 2.0 async declarative models (DeclarativeBase, per BED-01 DECISIONS.md D-01) + one hand-written Alembic revision (migrations/versions/001_initial_schema.py); 18-table shape 1:1 with the reference Prisma schema (PRD §8.4), snake_case table names, same unique constraints/nullability. Every table carries a String `id` primary key (app-generated uuid4 hex, matching the existing `app/api/ingest.py` id-generation convention) except the 3 tables PRD §8.4 gives a natural String primary key (system_metadata.key, persona_config.role, user_roles.email)."
  acceptance_spec: "PRD §8.4's itemized enumeration is the authoritative field/constraint list (R-007 schema-diff gate) — its own prose elsewhere (§Overview, §8, §8.4 lead-in, §Traceability) says '17-table/model shape', but the enumeration under §8.4 lists 10 rollup + 3 governance + 5 ingestion/auth/system = 18 named tables verbatim. Verified by direct count: the '17' prose is the stale figure, not this contract's itemized list — do not split the difference to 17 or 18-minus-one."
  deltas_from_prd_prose: "mau_series.as_of_timestamp and program_summary.as_of_timestamp are NOT itemized in PRD §8.4's per-table prose lines, but ARE part of this contract. Confirmed at /arh-human-review 2026-08-27 (BED-01 AF-02, pawar.pratik0903@gmail.com): every sibling rollup table carries as_of_timestamp, and these are rebuilt-from-usage_events rollups where a staleness marker is load-bearing. Settled, not drift — do not remove when diffing this contract against the PRD."
  type_mapping: "Prisma BigInt -> sqlalchemy.BigInteger; Prisma Json -> sqlalchemy.dialects.postgresql.JSONB (BED-01 ADR-0003, not plain JSON); Prisma String[] -> sqlalchemy.dialects.postgresql.ARRAY(String); discriminator/enum-like fields -> plain String, no Postgres ENUM type; timestamps -> DateTime(timezone=True)."
  tables:
    rollups:
      org_summary_rollup:
        constraint: "unique(org_id); singleton, org_id default 'org-1'"
        fields: [id String PK, org_id "String unique default 'org-1'", programs_using_ai_count Integer, programs_total Integer, total_token_consumption BigInteger, lines_of_code_generated BigInteger, releases_using_harness Integer, repos_with_harness_installed Integer, repos_total Integer, as_of_timestamp "DateTime(timezone=True)", created_at "DateTime(timezone=True)", updated_at "DateTime(timezone=True)"]
      token_series:
        constraint: "unique(org_id, month)"
        fields: [id String PK, org_id String, "month String (YYYY-MM)", value BigInteger, as_of_timestamp "DateTime(timezone=True)"]
      mau_series:
        constraint: "unique(org_id, month)"
        fields: [id String PK, org_id String, "month String (YYYY-MM)", developer Integer, architect Integer, product_manager Integer, engineering_manager Integer, as_of_timestamp "DateTime(timezone=True)"]
      program_summary:
        constraint: "unique(program_id)"
        fields: [id String PK, program_id "String unique", name String, icon String, type String, description String, monthly_token_sparkline "JSONB (ADR-0003)", tokens BigInteger, releases Integer, features Integer, active_contributors Integer, repos_with_harness_installed Integer, repos_total Integer, commands_executed Integer, lines_of_code_generated BigInteger, user_stories_delivered Integer, intervention_count "Integer nullable", tool_rejections "Integer nullable", as_of_timestamp "DateTime(timezone=True)"]
      program_releases:
        constraint: "index(program_id)"
        fields: [id String PK, program_id String, version String, "type String (major|minor|patch, plain String no enum)", date "DateTime(timezone=True)", story_count Integer, pr_count Integer, as_of_timestamp "DateTime(timezone=True)"]
      program_commands:
        constraint: "index(program_id)"
        fields: [id String PK, program_id String, name String, run_count Integer, period_start "DateTime(timezone=True)", period_end "DateTime(timezone=True)", as_of_timestamp "DateTime(timezone=True)"]
      program_members:
        constraint: "index(program_id)"
        fields: [id String PK, program_id String, user_id String, name String, role String, sessions Integer, tokens BigInteger, last_active_date "DateTime(timezone=True)", as_of_timestamp "DateTime(timezone=True)"]
      session_series:
        constraint: "unique(org_id, program_id, member_id, date)"
        fields: [id String PK, org_id String, program_id String, "member_id String nullable (nullable = org/program-wide rollup row)", date "DateTime(timezone=True)", session_time_seconds Integer, as_of_timestamp "DateTime(timezone=True)"]
      program_token_series:
        constraint: "unique(program_id, date)"
        fields: [id String PK, program_id String, date "DateTime(timezone=True)", tokens BigInteger, "input_tokens Integer default 0", "output_tokens Integer default 0", "cache_read_tokens Integer default 0", "cache_write_tokens Integer default 0", as_of_timestamp "DateTime(timezone=True)"]
      user_sessions:
        constraint: "unique(session_identifier)"
        fields: [id String PK, user_id String, program_id String, session_identifier "String unique", name String, started_at "DateTime(timezone=True)", duration_seconds Integer, tokens BigInteger]
    governance:
      program_artifacts:
        constraint: "unique(program_id, type)"
        fields: [id String PK, program_id String, "type String (prd|user_story|test_case|arch_diagram|api_spec)", count Integer, as_of_timestamp "DateTime(timezone=True)"]
      program_guardrails:
        constraint: "unique(program_id, name)"
        fields: [id String PK, program_id String, name String, "status String (Enforced|Warning|NotImplemented)", document_ref "String nullable", display_order Integer]
      org_constitution:
        constraint: "unique(org_id, category)"
        fields: [id String PK, org_id String, "category String (Constraints|Standard|Mandatory|Vision)", description String, item_count Integer, document_ref String, display_order Integer]
    ingestion_auth_system:
      usage_events:
        constraint: "unique(program_id, session_id, cmd_ts); index(program_id, ts); index(program_id, user); index(program_id, command); index(program_id, session_id). Source of truth every rollup table above is rebuilt from (A-002). Retention/archival explicitly out of scope for BED-01 (PRD R-001/NFR-014 gap, carried forward)."
        fields: [id String PK, program_id String, ts "DateTime(timezone=True)", cmd_ts "DateTime(timezone=True)", user String, session_id String, kind "String nullable", command String, feature "String nullable", duration_seconds Integer, outcome String, intervention_count "Integer nullable", files_created "Integer nullable", files_modified "Integer nullable", lines_added "Integer nullable", tool_rejections "Integer nullable", input_tokens "Integer nullable", output_tokens "Integer nullable", cache_read_tokens "Integer nullable", cache_write_tokens "Integer nullable", total BigInteger, models "JSONB nullable (ADR-0003)"]
      ingest_tokens:
        constraint: "unique(token_hash); index(user_email). No column stores the raw token (BED-01 AC-5, NFR-006)."
        fields: [id String PK, "token_hash String unique (SHA-256 hex, 64 chars)", label String, user_email String, "allowed_program_ids postgresql.ARRAY(String) (or literal '*' wildcard entry)", expires_at "DateTime(timezone=True) nullable", revoked_at "DateTime(timezone=True) nullable", last_used_at "DateTime(timezone=True) nullable"]
      system_metadata:
        constraint: "key is the literal primary key (e.g. 'ingestion')"
        fields: ["key String PK", last_successful_run_at "DateTime(timezone=True)"]
      persona_config:
        constraint: "role is the literal primary key"
        fields: ["role String PK", persona String]
      user_roles:
        constraint: "email is the literal primary key"
        fields: ["email String PK", role String, "source String default 'keycloak'", synced_at "DateTime(timezone=True)"]
```

### rollup-rebuild

```yaml
produced_by: BED-03
consumed_by: [ING-02, ING-06]
shape:
  mechanism: "rebuild_program_rollups(program_id) / rebuild_org_rollups() fully re-derive every rollup table from usage_events on every successful ingest write — never incremental patches (A-002, FR-BE-06/07, NFR-012)"
  invariant: "usage_events is append/upsert-only, unique on [program_id, session_id, cmd_ts]; rebuild is O(events for the affected program) per write"
```
