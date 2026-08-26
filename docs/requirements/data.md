### db-schema

```yaml
produced_by: BED-01
consumed_by: [BED-02, BED-03, BED-04, AUTH-02, AUTH-04, OVW-01, OVW-02, OVW-03, OVW-04, PGD-01, PGD-02, PGD-03, PGD-04, PGD-05, PGD-06, SHP-02, SHP-03, SHP-04, SHP-05, SHP-06, SHP-07, ING-01, ING-02, ING-03, ING-07, ING-08]
shape:
  mechanism: "SQLAlchemy 2.0 async declarative models + Alembic migrations; 18-table shape 1:1 with the reference Prisma schema (PRD §8.4), snake_case table names, same unique constraints/nullability"
  tables:
    rollups: [org_summary_rollup, token_series, mau_series, program_summary, program_releases, program_commands, program_members, session_series, program_token_series, user_sessions]
    governance: [program_artifacts, program_guardrails, org_constitution]
    ingestion_auth_system: [usage_events, ingest_tokens, system_metadata, persona_config, user_roles]
  acceptance_spec: "PRD §8.4's itemized enumeration is the authoritative field/constraint list (R-007 schema-diff gate) — its own prose elsewhere (§Overview, §8, §8.4 lead-in, §Traceability) says '17-table/model shape', but the enumeration under §8.4 lists 10 rollup + 3 governance + 5 ingestion/auth/system = 18 named tables verbatim. Verified by direct count: the '17' prose is the stale figure, not this contract's itemized list — do not split the difference to 17 or 18-minus-one."
```

### rollup-rebuild

```yaml
produced_by: BED-03
consumed_by: [ING-02, ING-06]
shape:
  mechanism: "rebuild_program_rollups(program_id) / rebuild_org_rollups() fully re-derive every rollup table from usage_events on every successful ingest write — never incremental patches (A-002, FR-BE-06/07, NFR-012)"
  invariant: "usage_events is append/upsert-only, unique on [program_id, session_id, cmd_ts]; rebuild is O(events for the affected program) per write"
```
