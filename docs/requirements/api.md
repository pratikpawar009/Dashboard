### api-conventions

```yaml
produced_by: BED-02
consumed_by: [OVW-01, OVW-02, OVW-03, OVW-04, PGD-01, PGD-02, PGD-03, PGD-04, PGD-05, PGD-06, SHP-02, SHP-03, SHP-04, SHP-05, SHP-06]
shape:
  range:
    dependency: "validate_range(request: Request, range: str = Query(...)) -> str @ app.dependencies.range — Depends(), not middleware, not per-router inline checks (FR-1)"
    allowed_values: ["7d", "30d", "90d"]
    rejection: "HTTPException(400, 'invalid_range') -> {\"error\": {\"code\": \"http_400\", \"message\": \"invalid_range\", \"details\": null}} via app.core.errors.error_body()/register_exception_handlers() — never FastAPI's default 422 (AC 2, FR-1)"
    window_helper: "range_to_start(range_value: str, now: datetime | None = None) -> datetime @ app.dependencies.range — start = now - timedelta(days={7,30,90}[range_value]); returns timezone-aware UTC (default reference datetime.now(UTC)); a caller-supplied naive `now` raises ValueError rather than being coerced (D-06, docs/features/BED-02/DECISIONS.md)"
    logging: "on rejection: logger.warning('invalid_range', extra={route, param: 'range', rejected_value}) — surfaced via JSONFormatter's extras merge (FR-3)"
    consistency: "identical 400 status + error body across every consumer of validate_range() (AC 7)"
  pagination:
    offset_limit: "get_offset_limit(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1)) -> tuple[int, int] @ app.dependencies.pagination — clamps limit to 50 (MAX_OFFSET_LIMIT), never rejects an over-max value (AC 3); MAX_OFFSET_LIMIT is importable only from app.dependencies.pagination, not re-exported on the app.dependencies package barrel"
    page_size: "get_page_params(page: int = Query(1, ge=1), page_size: int = Query(100, ge=1)) -> tuple[int, int] @ app.dependencies.pagination — clamps page_size to 100 (MAX_PAGE_SIZE), kept equal to app.api.activities.MAX_PAGE_SIZE (AC 4); MAX_PAGE_SIZE is importable only from app.dependencies.pagination, not re-exported on the app.dependencies package barrel — deliberately, since the name collides with app.api.activities.MAX_PAGE_SIZE (two distinct, numerically-equal constants)"
  derived_values:
    adoption_percent: "compute_adoption_percent(rollup: OrgSummaryRollup) -> dict @ app.services.rollup_compute — adoption_percent = programs_using_ai_count / programs_total * 100; None (not 0.0) when programs_total == 0 — no programs registered yet is not the same as measured-and-zero (D-07, docs/features/BED-02/DECISIONS.md). Consumers must render a null case, not assume a numeric adoption_percent."
    period_delta: "compute_period_delta(current_total, prior_total) -> dict @ app.services.rollup_compute — delta = (current_total - prior_total) / prior_total * 100 (percent change; None when prior_total == 0)"
    average: "compute_average(total, count) -> float @ app.services.rollup_compute — average = total / count (0.0 when count == 0). Returns a bare float, not a dict — the one rollup_compute function that diverges from D-02's raw+computed dict-merge default, since there is no separate raw field to merge it with."
    guardrail_summary: "compute_guardrail_summary(guardrails: Sequence[ProgramGuardrail]) -> dict @ app.services.guardrail_compute — 'X/Y passing' where passing = status == 'Enforced' (D-05, docs/features/BED-02/DECISIONS.md); PASSING_STATUS is importable only from app.services.guardrail_compute, not re-exported on the app.services package barrel. An empty guardrails sequence returns passing_count=0, total_count=0, summary='0/0 passing' — never None: unlike adoption_percent this performs no division, so there is no zero-denominator to guard against (D-08, docs/features/BED-02/DECISIONS.md)."
    layer: "services/api/app/services/*.py only — never left for the frontend to compute (AC 5)"
  formatting:
    numeric: "format_number(value: int | float) -> str @ app.utils.format — M/K suffix (e.g. 2500 -> '2.5K', 1_500_000 -> '1.5M'). Full boundary contract (D-09, docs/features/BED-02/DECISIONS.md): one decimal is always kept incl. a trailing .0 (2000 -> '2.0K'); bucket is chosen from the rounded quotient that will actually render, promoting up a bucket when that quotient reaches 1000, so bucket and value never disagree (999_999 -> '1.0M', not '1000.0K'); values below 1,000 render as a bare rounded int ('999 -> 999', '0 -> 0'); negatives keep their sign and bucket on abs(value) ('-2500 -> -2.5K'). Known limitation, not fixed: M is the largest bucket (no B/billions bucket) and promotion stops there, so a magnitude whose M-quotient itself rounds to >= 1000.0 (roughly >= 999_950_000) renders unbounded and un-abbreviated, e.g. 1_000_000_000 -> '1000.0M' — open/untriaged product question, see AF-04 (docs/features/BED-02/FLAGS.md)."
    duration: "format_duration(minutes: int) -> str @ app.utils.format — h/m suffix (e.g. 125 -> '2h 5m'); exact hours drop the minutes term (120 -> '2h'); 0 -> '0m'. Raises ValueError on negative minutes rather than coercing — divmod floors toward -inf and would otherwise silently render a negative duration as a positive one (D-09, docs/features/BED-02/DECISIONS.md). Consumers must not pass a negative value without expecting/handling this exception."
    layer: "backend-only (FR-2) — no equivalent frontend formatting utility exists or should be added (AC 6)"
```

Wiring into consumer routers (OVW/PGD/SHP endpoints) is explicitly each downstream story's own scope — this shape is the contract they build against, not yet mounted on any route.

### freshness-api

```yaml
produced_by: BED-04
consumed_by: [OVW-01, ARC-01, DEV-01, PMD-01, EMD-01]
shape:
  accessor: "class FreshnessAccessor @ app.services.freshness — async def get_last_successful_run(self) -> datetime; no HTTP route (a read-only in-process service, not a router)"
  construction: "FreshnessAccessor(*, session_factory: async_sessionmaker[AsyncSession] | None = None) -- defaults to app.core.db.SessionLocal; each downstream story owns constructing/sharing its own instance (BED-04 wires no app.state singleton, since no route consumes it yet)"
  fields: { last_successful_run_at: "datetime, timezone-aware (UTC), sourced from system_metadata.key='ingestion' -- a raw datetime, not a pre-formatted display string" }
  cache: "300s TTL tracked via time.monotonic(), asyncio.Lock double-check on a cache miss (mirrors app.core.persona_resolver.PersonaResolver's cache shape). TTL expiry is the only invalidating event -- the writer is out-of-process (CLI ingester / MCP push) and cannot invalidate an in-process cache, so the TTL length is the worst-case apparent staleness."
  error: "row absent -> raises HTTPException(status_code=500, detail=_NOT_RUN_MESSAGE) where _NOT_RUN_MESSAGE = 'ingestion job may not have run yet' (module constant, app.services.freshness), rendered by the existing StarletteHTTPException handler as {\"error\": {\"code\": \"http_500\", \"message\": \"ingestion job may not have run yet\", \"details\": null}}. Also emits logger.warning() with that same constant on every row-absent call. Never negative-cached -- every call re-queries system_metadata while the row stays absent."
  timeout: "the single system_metadata read is bounded by an explicit 3.0s asyncio.wait_for timeout (D-04, matching app.core.persona_resolver's Tier-3 bound) -- on timeout, raises HTTPException(status_code=500, detail=_QUERY_TIMEOUT_MESSAGE) where _QUERY_TIMEOUT_MESSAGE = 'ingestion freshness query timed out' (module constant, app.services.freshness), a distinct message from _NOT_RUN_MESSAGE since a stalled read is a different outcome from an absent row. Also emits logger.warning() with that same constant. Never negative-cached -- every call re-queries after a timeout."
  no_rbac: "read-only, no persona/role gating -- the freshness timestamp renders on every dashboard view regardless of persona"
```

### programs-api

```yaml
produced_by: AUTH-04
consumed_by: [PGD-01, EMD-01]
shape:
  endpoint: "GET /api/programs"
  scoping: "cio sees all programs; every other persona sees only programs matching session.groups program list"
  fields: { program_id, label, href, dotStyle }
  authority: "ADR-0005 — the switcher-list bindings of PGD-01 progOptions / EMD-01 projOptions"
  excluded: "type, description — bound by program-detail-api header and persona-shell program_context, not by this list"
  client_derived: "current, rowStyle — route-dependent, computed by comparing href against the current route"
```

### persona-shell

```yaml
produced_by: SHP-01
consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01]
shape:
  component: "PersonaDashboardShell(props) @ apps/web/src/components/PersonaDashboardShell.tsx — presentational, no fetching, no persona conditionals of its own"
  props:
    signedInUser: "{ name: string; jobTitle: string } | undefined — undefined pre-AUTH-01-amendment or pre-resolution (renders the FR-5 neutral identity fallback, never a placeholder name/jobTitle); PROVISIONAL field names, pending the AUTH-01 session-contract amendment (SHP-01 Constraints/C-1, DECISIONS.md D-01). Isolated behind apps/web/src/types/persona.ts so a rename there is a two-file change, not a wide refactor."
    persona: "string | undefined — undefined means session/persona-resolver output has not yet resolved (FR-5 loading gate: suppresses the identity bar, persona tag, subtitle, and program context entirely, no skeleton). A defined value is passed to formatPersonaTag(); one of 'architect' | 'developer' | 'product-manager' | 'engineering-manager' renders normally, any other value (including 'cio', or whatever sentinel the composing page passes after catching AUTH-02's PersonaNotFoundError) throws PersonaTagError, rendered as the one neutral 'Persona unavailable' badge plus an aria-live='assertive' announcement (FR-2, FR-5, DECISIONS.md D-03)."
    program: "{ icon: string; name: string; type: string; description: string } — one prop name across all 4 pages (never prog/proj, C-4); data only, no avatarStyle/typeChip fields. The shell derives avatarStyle/typeChip color from program.type via its own docs/design/tokens.md-sourced lookup (FR-4, DECISIONS.md D-04), ignoring any style field the prop might carry. The composing page resolves this fully before render (C-3) — the shell owns no loading/empty state for it; an absent/undefined program while persona has resolved is a caller error, not a shell-rendered state."
  derived_internally:
    tag_subtitle_color: "formatPersonaTag(persona) @ apps/web/src/lib/formatPersonaTag.ts -> { tag, subtitle, color, background } — 'Architect'|'Developer'|'Product Manager'|'Eng Manager' tags, the 4 subtitle literals verbatim (incl. lowercase 'm' in 'Engineering manager overview'), throws PersonaTagError for 'cio'/any other value (FR-2, DECISIONS.md D-02)"
    initials: "deriveInitials(signedInUser.name) @ apps/web/src/lib/deriveInitials.ts — uppercase first letter of each of the first 2 space-separated tokens ('Devon Rao' -> 'DR'); a single-token name yields that one letter only (FR-3). Rendered inside a 34x34px circle colored via formatPersonaTag(persona).color. Never computed until signedInUser resolves."
    program_style: "getProgramStyle(program.type) @ apps/web/src/lib/programStyle.ts -> { avatarStyle, typeChip } — keyed on 'Migration'|'Greenfield feature development'|'Brownfield feature development'|'Maintenance' (FR-4, DECISIONS.md D-04)"
  states:
    loading: "persona === undefined — renders only the static product header (brand mark + 'AgentRise Harness'/'AI SDLC Governance'); identity bar, persona tag, subtitle, and program context are all absent, no skeleton (FR-5)"
    error: "persona is defined but not one of the 4 valid personas — neutral gray 'Persona unavailable' badge in place of the persona tag, no subtitle, plus a visually-hidden aria-live='assertive' region reading 'Unable to load your dashboard view.' (FR-5). Independent of the identity-bar/program-context axes below — both still render per their own rules."
    populated: "persona is one of the 4 valid personas — tag/subtitle/program context render normally; identity bar renders signedInUser's name/jobTitle/initials if defined, else its own neutral fallback (a plain gray circle, no initials, aria-hidden, DECISIONS.md D-05) — independent of persona validity, per the Rollout plan's no-feature-flag, data-presence-driven design"
  out_of_scope: "fetching/resolving session, persona, or program (owned by ARC-01/DEV-01/PMD-01/EMD-01, not yet planned — SHP-01 Constraints/condition 2); the 'Switch program' control (EMD-01 renders it as a sibling after the shell, C-4)"
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
