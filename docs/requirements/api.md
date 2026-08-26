### api-conventions

```yaml
produced_by: BED-02
consumed_by: [OVW-01, OVW-02, OVW-03, OVW-04, PGD-01, PGD-02, PGD-03, PGD-04, PGD-05, PGD-06, SHP-02, SHP-03, SHP-04, SHP-05, SHP-06]
shape:
  range: "range=7d|30d|90d on every time-series/list endpoint; 400 via explicit check (never FastAPI's default 422) on an invalid value (FR-BE-02)"
  pagination: "offset/limit (max 50, per-endpoint) and page/page_size (max 100) where applicable (FR-BE-03)"
  derived_values: "adoption %, deltas, averages, 'X/Y passing' computed server-side only, never client-side (FR-BE-04)"
  formatting: "M/K numeric and h/m time formatting applied consistently — pick one layer (frontend display-only or backend pre-formatted) and do not mix (FR-BE-08)"
```

### freshness-api

```yaml
produced_by: BED-04
consumed_by: [OVW-01, ARC-01, DEV-01, PMD-01, EMD-01]
shape:
  endpoint: "cached accessor over system_metadata singleton row (key='ingestion')"
  fields: { last_successful_run_at: "datetime" }
  error: "raises a clear 'ingestion job may not have run yet' error if the row is absent"
```

### programs-api

```yaml
produced_by: AUTH-04
consumed_by: [PGD-01, EMD-01]
shape:
  endpoint: "GET /api/programs"
  scoping: "cio sees all programs; every other persona sees only programs matching session.groups program list"
```

### persona-shell

```yaml
produced_by: SHP-01
consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01]
shape:
  fields: { product_header, signed_in_user: { name, role }, persona_tag, subtitle, program_context: { icon, name, type, description } }
```

### overview-summary-api

```yaml
produced_by: OVW-01
consumed_by: []
shape:
  endpoint: "GET /api/overview/summary"
  source: "org_summary_rollup singleton (org_id='org-1'); all-zero graceful response if row missing"
  fields: { programs_using_ai: {count, total, adoption_percent}, total_token_consumption, lines_of_code_generated, releases_using_harness, repos_with_harness_installed_over_total }
```

### overview-token-series-api

```yaml
produced_by: OVW-02
consumed_by: []
shape:
  endpoint: "GET /api/overview/token-series"
  fields: "exactly 12 {month, value} points, zero-padded, plus period_over_period_change"
```

### overview-mau-series-api

```yaml
produced_by: OVW-03
consumed_by: [SHP-07]
shape:
  endpoint: "GET /api/overview/mau-series"
  fields: "12 {month, developer, architect, product_manager, engineering_manager} points, plus period_over_period_change"
  note: "role segmentation fixed to these 4 columns until SHP-07 (Could Have) extends it via migration"
```

### program-board-api

```yaml
produced_by: OVW-04
consumed_by: []
shape:
  endpoint: "GET /api/overview/program-board"
  source: "program_summary rows ordered by tokens desc"
```

### program-detail-api

```yaml
produced_by: PGD-01
consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01]
shape:
  endpoint: "GET /api/overview/program-detail/{program_id}"
  fields: "header (icon, name, type, description) + 7 to-date summary cards (tokens, features, releases, repos, commands, LOC, stories)"
  invariant: "byte-identical response regardless of CIO vs Engineering Manager caller; no persona-branching logic (FR-PD-17)"
```

### program-token-trend-api

```yaml
produced_by: PGD-02
consumed_by: [EMD-01]
shape:
  endpoint: "program-level daily token series for the selected range, default 30d; returns period total + avg/day"
```

### program-releases-api

```yaml
produced_by: PGD-03
consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01]
shape:
  endpoint: "GET /api/program-detail/{program_id}/releases?range=&offset=&limit=  (default offset=0, limit=20, max 50)"
  fields: "version, type, status indicator, date, story_count, pr_count; total count"
```

### program-commands-api

```yaml
produced_by: PGD-04
consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01]
shape:
  fields: "program-level command name + run_count for the selected range, total run count; distinct from personal-usage-api's per-user commands"
```

### program-team-api

```yaml
produced_by: PGD-05
consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01, SHP-07]
shape:
  fields: "member name, role, sessions, tokens, avg/session, for the selected range"
```

### program-session-series-api

```yaml
produced_by: PGD-06
consumed_by: [EMD-01]
shape:
  fields: "session_series rows (nullable member_id = org/program rollup); filterable by member_id; period total + avg/day"
```

### personal-usage-api

```yaml
produced_by: SHP-02
consumed_by: [ARC-01, DEV-01, PMD-01, PGD-05]
shape:
  endpoint: "GET /api/personal-usage/{user_id}"
  fields: "cards (sessions, total_time, total_tokens, avg_tokens_per_session) + daily token chart + daily session-time chart + commands, ranged 7d/30d/90d default 30d"
  authz_note: "SHP-02's own self-view calls this gated by rbac-checks' individual_usage_visibility (self always; else cio only, FR-AUTH-07). PGD-05 reuses this same endpoint/shape as the Project Team per-member drill-down popup — same contract, no new interface — gated instead by rbac-checks' member_in_program_visibility (program check AND (self OR cio), FR-AUTH-08); denials logged as member_view_denied, not individual_view_denied."
```

### personal-sessions-api

```yaml
produced_by: SHP-03
consumed_by: [ARC-01, DEV-01, PMD-01]
shape:
  endpoint: "GET /api/personal-usage/{user_id}/sessions?page=&page_size= (max 100)"
  fields: "session name/description, identifier, date, duration, tokens — paginated"
```

### artifacts-api

```yaml
produced_by: SHP-04
consumed_by: [ARC-01, DEV-01, PMD-01]
shape:
  endpoint: "GET /api/artifacts/{program_id}"
  fields: "5 canonical types (prd, user_story, test_case, arch_diagram, api_spec) with counts, zero-count types included"
```

### guardrails-api

```yaml
produced_by: SHP-05
consumed_by: [ARC-01, DEV-01, PMD-01]
shape:
  endpoint: "GET /api/guardrails/{program_id}"
  fields: "overall 'X/Y passing' (pass = Enforced or Warning) + per-guardrail name, status (Enforced|Warning|NotImplemented), document_ref"
```

### constitution-api

```yaml
produced_by: SHP-06
consumed_by: [ARC-01, DEV-01, PMD-01]
shape:
  endpoint: "GET /api/constitution"
  fields: "4 categories (Constraints, Standard, Mandatory, Vision), each with description, item_count, document_ref"
```

### ingest-files-api

```yaml
produced_by: ING-02
consumed_by: [ING-04, ING-06, ING-09]
shape:
  endpoint: "POST /api/ingest/files  {program_id, kind:'activity', rows}"
  auth: "ingest-token-auth bearer"
  limits: "5000 rows/request cap, 413 over"
  response: "received/valid/inserted/updated/rejected counts + reasons + rollup summaries"
```

### ingest-artifacts-api

```yaml
produced_by: ING-03
consumed_by: [ING-04]
shape:
  endpoint: "POST /api/ingest/artifacts  {program_id, kind:'artifacts', counts, as_of}"
  auth: "ingest-token-auth bearer"
  validation: "counts validated against the 5 canonical artifact types; one-transaction idempotent upsert"
```

### mcp-tools

```yaml
produced_by: ING-04
consumed_by: [ING-05]
shape:
  server: "services/mcp-server, package agentrise_mcp, FastMCP streamable HTTP, default 0.0.0.0:3010, path /mcp"
  tools: ["push_activity(program_id?, workspace_root?)", "push_artifacts(program_id?, workspace_root?)"]
```

### admin-scan-api

```yaml
produced_by: ING-07
consumed_by: []
shape:
  endpoint: "POST /api/admin/scan-repos"
  auth: "ingest-token-auth bearer"
  effect: "scans configured GitHub org for Harness installation; updates org rollup repo counts"
```
