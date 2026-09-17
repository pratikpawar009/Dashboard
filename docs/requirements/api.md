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
produced_by: [SHP-01, OVW-05]
consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01, OVW-05, PGD-07]
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
  cio_persona_note: "OVW-05 (docs/prd/cio-shell-logout-and-persona-resolution.md) makes `cio` a FIFTH RENDERABLE PERSONA, additively. It is added to `VALID_PERSONAS` (apps/web/src/types/persona.ts) and gets its own `PERSONA_DISPLAY` entry (apps/web/src/lib/formatPersonaTag.ts): tag `CIO / CXO`, avatar colour `#0f1a2e`, plus a new fifth `jobTitle` field (`Chief Information Officer`) that every one of the five entries carries -- see `job_title_source_note` below. SUPERSEDES two statements left verbatim above per the do-not-rewrite-contract-field-text precedent (RTM Decisions 2026-09-04, 2026-09-09): (a) the `persona` prop's 'any other value (including cio ...) renders PersonaTagError / the neutral badge' clause, and (b) `derived_internally.tag_subtitle_color`'s 'throws PersonaTagError for cio'. After OVW-05, `cio` renders normally; only genuinely unresolvable values throw. It also DELETES the factually wrong premise in `formatPersonaTag`'s own docstring ('the CIO Portfolio mockup has no persona tag/subtitle region at all -- so a cio value reaching this function is an invariant violation, not a fifth persona to render'), verified false against the decoded mockup: `dashboards/CIO Portfolio Dashboard.html`'s BRAND BAR and HEADER regions are structurally identical to the Architect mockup's, and its `#0f1a2e` avatar sits exactly where `#6a4fd0` (== PERSONA_DISPLAY.architect.color) sits in the other. Nothing about the four existing personas changes -- ARC-01/DEV-01/PMD-01/EMD-01 never pass `cio`, so this is a fifth map key, not a behaviour change for them."
  org_header_region: "OVW-05 adds a SECOND, org-level header variant, because the shipped `headerRegion` is gated on `!isLoading && program !== undefined` -- structurally unsatisfiable for an org-level page that has no single program (OVW-01 D-04 made `program` optional for exactly this page, which is what leaves the region unrenderable). The CIO variant is a DIFFERENT composition, not the same region with a null program -- verified against the decoded markup: CIO renders `[19px/700 page title] [CIO / CXO pill]` on one line then a 12.5px/#7a828f subtitle beneath, whereas ARC renders `[persona pill] persona-subtitle` on one line then the program avatar/name/type-chip/description block. Sketch: the persona-owned literals (pill text, subtitle) come from `PERSONA_DISPLAY.cio` like every other persona's do; the page TITLE (`Adoption Overview`) is a prop from the composing page, since it names the page rather than the persona. Both regions stay mutually exclusive and neither gains a persona conditional inside PersonaDashboardShell.tsx (research condition C-7 holds -- the variant is selected by prop presence, not by comparing `persona` to a literal)."
  identity_block_unblocked: "the brand bar's signed-in identity block is already fully implemented and already correct (name/jobTitle text + 34x34 initials circle coloured by `formatPersonaTag(persona).color`); it never renders on `/overview` for one reason only -- `AdoptionOverview` omits `persona`, so `isLoading = persona === undefined` is permanently true and the whole block is suppressed by FR-5. OVW-05 supplies `persona` and `signedInUser` from `session-identity-api` (AUTH-07) and the existing code renders. No new identity markup is authored."
  job_title_source_note: "CONFIRMED by user 2026-09-10. `signedInUser.jobTitle` is sourced from `PERSONA_DISPLAY[persona].jobTitle`, a frontend per-persona presentation constant -- NOT from the wire, NOT an OIDC user attribute, NOT `program_roster.team[].role`. `session-identity-api` therefore ships `name` and `persona` only. The five values are FIXED and are PLAIN ROLE NAMES, deliberately not the mockup literals: `cio` -> 'Chief Information Officer', `architect` -> 'Architect', `developer` -> 'Developer', `engineering-manager` -> 'Engineering Manager', `product-manager` -> 'Product Manager'. Two of the six decoded brand bars are knowingly diverged from -- see `job_title_divergence_note` below; this is the one place in this contract where the mockup is NOT the contract, so it is called out rather than left for a reader to discover as drift. Note also that `engineering-manager` carries TWO different strings on purpose and neither is a typo for the other: `tag` is 'Eng Manager' (byte-exact from the mockup's pill) while `jobTitle` is 'Engineering Manager' (the plain role name) -- do not 'fix' either to match the other."
  job_title_divergence_note: "DELIBERATE, USER-CONFIRMED DIVERGENCE FROM THE MOCKUPS (2026-09-10), recorded loudly because CLAUDE.md § Design system otherwise makes the mockup the contract -- same discipline as OVW-01-FR-2's presentation-vs-data divergence, which likewise overrode canvas bindings with a stated authority. Superseded literals, quoted so the diff is unambiguous: the Architect mockup's brand bar reads **'Principal Architect'** and the Developer mockup's reads **'Senior Developer'**; this contract ships 'Architect' and 'Developer' instead. Reason (user's): the system holds NO seniority data for anyone -- not in the OIDC claims, not in `program_roster` (whose `role` is a raw slug, `program-roster-schema` `role_semantics`), nowhere -- so it must never assert one. A junior developer must not read as 'Senior Developer' in their own brand bar. Evidence that the two seniority-bearing literals are the outliers rather than the rule: THREE of the five persona mockups already carry the plain role name ('Chief Information Officer', 'Engineering Manager', 'Product Manager'), so this change aligns five values on one rule instead of transcribing two exceptions. The mockup files are NOT edited (not this pipeline's artifact); the divergence lives here and in RTM Decisions 2026-09-10."
  program_detail_brand_bar: "PGD-07 (same source) is the SECOND consumer of the identity block, and its own row exists because a shared-shell fix does NOT reach it by construction. Verified, not assumed: `AdoptionOverview.tsx` is the ONLY non-test file in `apps/web/src` that renders `PersonaDashboardShell` -- `ProgramDetailView.tsx` renders its own `<div className={styles.wrapper}>` holding `ProgramDetailHeader` + `ProgramSummaryCards`, so Program Detail is missing the ENTIRE `<!-- BRAND BAR -->` region (no logo tile, no 'AgentRise Harness'/'AI SDLC Governance', no identity block), not merely the identity half. CRITICAL CONSTRAINT for that story: it passes `program: undefined`. The Program Detail mockup's `<!-- HEADER -->` region is ALREADY correctly shipped by `ProgramDetailHeader` (its own docstring cites 'DESIGN.md Region 2, mockup <!-- HEADER -->'), and this shell's header region is gated on `program !== undefined` -- so passing `program` would double-render the program avatar/name/type-chip/description. The brand bar is widened; the header is not touched. Second constraint: the mockup's brand bar happens to show the CIO (`Elena Vasquez` / `#0f1a2e`) because it was drawn from the CIO's drill-down path, but Program Detail is reachable by other personas (EMD-01, and `program-detail-api` is byte-identical across personas) -- so it renders the ACTUAL signed-in persona from `session-identity-api`, never a hardcoded CIO. Same rule as `session-identity-api`'s `persona` field states for `/overview`."
  page_title_prop: "pageTitle?: string -- the composing page's title (e.g. \"Adoption Overview\"). Selects the org-header variant (title + persona pill on one line, persona subtitle beneath) when `pageTitle !== undefined && program === undefined && !isLoading` -- selection is by prop presence only, never a `persona === 'cio'` (or any other persona-literal) conditional; none exists in `PersonaDashboardShell.tsx` and none may be added (research condition C-7). Mutually exclusive with the shipped `program !== undefined` program-header variant. Authored by OVW-05 as co-producer (produced_by: [SHP-01, OVW-05])."
  sign_out_control: "Zero-JS control: `<form action=\"/logout\" method=\"get\"><button type=\"submit\" aria-label=\"Sign out\">Sign out</button></form>`. Rendered as the last child of the identity row, a SIBLING of the `signedInUser` ternary -- outside it -- so it appears in BOTH the populated and the D-05 neutral-fallback branch; gated only by `!isLoading`, so it disappears with the rest of the identity block when `persona` is unresolved. Targets the existing `GET /logout` Route Handler (AUTH-07) -- adds no new logout logic, no second cookie-clear path. The GET-form shape (not a client `<button onClick>`) is what keeps `PersonaDashboardShell` a Server Component with a props-only, no-fetch contract. `aria-label` byte-matches the visible text (WCAG 2.5.3 Label in Name). Recorded deviation from the design source: none of the six mockups carries a sign-out affordance; added by explicit user direction (docs/stories/OVW-05.md § Decision log, 2026-09-11)."
```

### overview-summary-api

```yaml
produced_by: OVW-01
consumed_by: []
shape:
  endpoint: "GET /api/overview/summary"
  response_model: "OrgSummaryResponse @ app/schemas/org_summary.py (OVW-01/DECISIONS.md D-01/D-02, PLAN.md T-01)"
  top_level: "{ cards: list[OrgSummaryCard], programs_using_ai: ProgramsUsingAi } -- two structures, not one flat object (FR-1). programs_using_ai is kept separate from cards because it also drives the Adoption Level indicator, not just its own summary card."
  cards: "list[OrgSummaryCard { glyph: str, value: str, label: str, sub: str | None }], exactly 5 entries -- FOUR fields, unlike program-detail-api's genuinely three-field ProgramSummaryCard (that mockup binds only s.glyph/s.label/s.value; the CIO Portfolio mockup's ORG SUMMARY template also binds k.sub, DECISIONS.md D-01). Mockup order: (1) programs_using_ai, (2) total_token_consumption, (3) lines_of_code_generated, (4) releases_using_harness, (5) repos_with_harness_installed_over_total. glyph/label are fixed presentation constants extracted directly from dashboards/CIO Portfolio Dashboard.html's embedded sample-data script (DECISIONS.md D-01): (\"▦\", \"Programs using AI SDLC\"), (\"⬡\", \"Total token consumption\"), (\"</>\", \"Lines of code generated by Harness\"), (\"⤴\", \"Releases using Harness\"), (\"❯\", \"Repos with Harness installed\") -- order is the contract, never re-sorted by a consumer. value/sub -- CORRECTED 2026-09-10 per DECISIONS.md D-02 (the prior revision of this section had this backwards, see the note at the end of this field): card 1 (programs_using_ai) value is the literal ratio \"{count} / {total}\", EXEMPT from format_number(), and is the ONLY card carrying a non-null sub (\"{pct}% adoption\"; null when programs_total == 0, since adoption_percent is None then and the mockup's sc-if omits the element). Cards 2-5 (total_token_consumption, lines_of_code_generated, releases_using_harness, repos_with_harness_installed_over_total) pass through format_number() (api-conventions) and always ship sub: null -- card 5 is a PLAIN count, NOT a ratio, despite its `_over_total` id (the id names AC-1's enumeration order, not the rendering). This section previously stated the reverse -- format_number() on card 1, a ratio on card 5 -- sourced from an FR-1 revision that read only the mockup's template bindings, not its embedded sample-data script; DECISIONS.md D-02 has the full correction history."
  programs_using_ai: "{ count: int, total: int, adoption_percent: float | None } -- count/total are raw ints (needed verbatim for the Adoption Level headline/legend); adoption_percent is None, never 0.0, when total == 0 (api-conventions derived_values.adoption_percent) -- covers both the missing-row (AC-2) and genuinely-zero-programs cases. Ships as a raw number, never a pre-formatted percent string (FR-1 Decision) -- the frontend composes the headline/subtitle/bar/legend display text from these raw fields (FR-2, DECISIONS.md D-05/D-06), the API ships no color/style/pre-formatted-percent field."
  source: "org_summary_rollup singleton (org_id='org-1'). Row present -> compute_adoption_percent() (api-conventions) derives programs_using_ai. Row absent (AC-2, fresh/never-ingested org) -> all-zero fallback: card 1 value '0 / 0' sub null, cards 2-5 value '0' sub null, programs_using_ai = {count:0, total:0, adoption_percent:None}."
  freshness: "FreshnessAccessor.get_last_successful_run() (freshness-api, BED-04) is called exactly once per request, unconditioned by whether org_summary_rollup returned a row (FR-3) -- always BEFORE the org_summary_rollup query, so a missing system_metadata 'ingestion' row (AC-7) raises HTTPException(500, 'ingestion job may not have run yet') even on an otherwise-valid all-zero payload (the fully-fresh-database case). Nothing from this call reaches the response body (AC-6 is backend-only, no freshness timestamp renders anywhere on the page -- resolved research C-1)."
  rbac: "org_access(current_user) (rbac-checks/AUTH-03) gates the entire response -- cio only; every other persona 403 with no data body (AC-3). Logs rbac_check_org_access on every request, both outcomes (AC-8, NFR-011)."
  errors: "403 (non-cio persona, no data body) -> org_access's own HTTPException; 500 'ingestion job may not have run yet' (no system_metadata 'ingestion' row) -> FreshnessAccessor's HTTPException, app/core/errors.py's existing envelope, no new error shape; 401 (missing/invalid bearer) -> get_current_user's existing behavior."
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
  response_model: "ProgramDetailResponse @ app/schemas/program_detail.py (PGD-01/DECISIONS.md D-06, promoted ADR-0007)"
  header: "ProgramDetailHeader { icon: str, name: str, type: str, description: str } -- verbatim program_summary columns (BED-01/db-schema); no avatarStyle/typeChip on the wire -- consumers derive those client-side via apps/web/src/lib/programStyle.ts::getProgramStyle(type), matching the persona-shell/program_context convention already established by SHP-01 (D-05)"
  summary: "list[ProgramSummaryCard { glyph: str, value: str, label: str }], exactly 7 entries, mockup order is part of the contract: (1) tokens, (2) features, (3) releases, (4) repos_with_harness_installed, (5) commands_executed, (6) lines_of_code_generated, (7) user_stories_delivered. glyph/label are fixed presentation constants owned by the producer (mirrors AUTH-04's dot_style_for_program precedent of shipping presentation data server-side) -- consumers render via a plain map/for-each over `summary`, no per-consumer glyph/label duplication. value: cards 1/2/3/5/6/7 pass through format_number() (BED-02/api-conventions); card 4 (repos_with_harness_installed) renders as the literal ratio string \"{repos_with_harness_installed} / {repos_total}\" and is EXEMPT from format_number()"
  invariant: "byte-identical response regardless of CIO vs Engineering Manager caller; no persona-branching logic (FR-PD-17). The optional X-Program-Switch-From request header (D-07) affects ONLY which structured log event fires server-side (program_switch vs program_drilldown) -- it never changes response content, so it does not violate the byte-identical invariant"
  rbac: "program_visibility(current_user, program_id) (rbac-checks/AUTH-03) called once with the REAL program_id (unlike programs.py's sentinel usage) -- open-aggregate, never denies; program-membership scoping is explicitly out of scope (Clarification C-3)"
  errors: "unknown program_id -> HTTPException(404) -> app/core/errors.py's existing envelope {\"error\": {\"code\": \"http_404\", \"message\": ..., \"details\": null}} -- no new envelope shape"
  observability: "program_drilldown {program_id} logged when X-Program-Switch-From is absent (initial page load); program_switch {from_program_id, to_program_id} logged when present (switcher-triggered reload) -- mutually exclusive, exactly one fires per successful (200) request, neither fires on a 404 (D-07)"
```

### program-token-trend-api

```yaml
produced_by: PGD-02
consumed_by: [EMD-01]
shape:
  endpoint: "GET /api/overview/program-detail/{program_id}/token-trend?range=7d|30d|90d (default 30d, via a story-local _range_with_default wrapper around the shared validate_range()) -- a SIBLING route on the existing overview router (app/api/overview.py, prefix=/api/overview), not a new program_detail.py router file (DECISIONS.md D-01)"
  response_model: "ProgramTokenTrendResponse @ app/schemas/program_detail.py (PGD-02/DECISIONS.md D-02)"
  points: "list[ProgramTokenPoint { date: str, tokens: int }], one entry per calendar day in the selected range, oldest-to-newest -- zero-padded: a day with no program_token_series row still gets its own point with tokens: 0, never omitted, so points always has exactly 7/30/90 entries regardless of how sparse the program's data is; a program_id with NO data at all still returns a full all-zero series, never an empty array"
  period_total: "int -- raw sum of tokens across the range (NOT format_number()-formatted)"
  avg_per_day: "int -- round(period_total / num_days), where num_days is the range's FIXED day-count (7/30/90) derived from range_to_start()'s fixed-offset math, NOT the count of days that actually had data (DECISIONS.md D-03)"
  raw_int_divergence: "period_total, avg_per_day, and points[].tokens are RAW INTEGERS, not format_number()-formatted strings -- a deliberate, scoped departure from this API's usual 'values arrive pre-formatted' convention (docs/design/README.md). This endpoint does NOT reuse personal-usage-api's DailyTokenPoint/DailyTokenSeries shapes (DECISIONS.md D-02) -- two shapes for the same daily-series concept now exist in the codebase on purpose. The frontend owns magnitude formatting for these three fields (DECISIONS.md D-04)."
  source: "one grouped SELECT date_trunc('day', date), sum(tokens) FROM program_token_series WHERE program_id = :program_id AND date >= :range_start GROUP BY 1, backed by the existing uq_program_token_series_program_id_date unique index's leading program_id column -- no N+1, no per-day queries"
  rbac: "program_visibility(current_user, program_id) (rbac-checks/AUTH-03) called once with the real program_id -- open-aggregate, any authenticated session, never denies and never filters by current_user.programs; byte-identical response across every persona (AC-7)"
  errors: "400 invalid_range if range is outside {7d,30d,90d}, via the shared validate_range() envelope -- always this explicit 400, never FastAPI's default 422; 401 if the bearer token is missing or invalid. No 404 for an unknown program_id, unlike the sibling program-detail-api above -- the handler calls fetch_program_token_trend() directly after the RBAC gate with no existence check, so an unknown program_id returns 200 with a full all-zero series, not a 404 (verified against app/api/overview.py::get_program_token_trend / app/services/program_detail_token_trend.py::fetch_program_token_trend)"
```

### program-releases-api

```yaml
produced_by: PGD-03
consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01]
shape:
  endpoint: "GET /api/overview/program-detail/{program_id}/releases?range=7d|30d|90d&offset=&limit= -- a SIBLING route on the existing overview router (app/api/overview.py, prefix=/api/overview), matching PGD-01/PGD-02's pattern, not a standalone /api/program-detail/... route (research Condition C-1, DECISIONS.md). range default 30d via the shared _range_with_default/validate_range dependency; offset default 0; limit default 20 (DECISIONS.md D-01 -- a story-local Query default, NOT a change to app/dependencies/pagination.py::get_offset_limit's shared 50 default), clamped to 50 via the shared MAX_OFFSET_LIMIT clamp, never rejected"
  response_model: "ProgramReleasesResponse @ app/schemas/program_releases.py (PGD-03/DECISIONS.md D-02)"
  items: "list[ProgramReleaseItem { ver: str, label: str, dot: str, date: str, stories: str, prs: str }] -- mockup field names verbatim, NOT program_releases column names (version->ver, story_count->stories as a string, pr_count->prs as a string). date is pre-formatted \"Jul 15\" (month abbreviation + day, no year). label/dot are derived server-side from type via the fixed 3-entry vocabulary below (DECISIONS.md D-03) -- never client-derived"
  tag_color_tag_bg: "tagColor: str, tagBg: str -- hoisted to the TOP LEVEL of the response (not per-row), since they are the program's theme colours and identical across every row for a given program (DECISIONS.md D-02, corrects research Risk #3's open question)"
  relTotal: "str -- count of releases within the active range window, NOT program-lifetime total (distinct from program-detail-api's card 3 'Releases done via Harness'). MUST share the identical date-window predicate with the items query (FR-PGD03-6) -- independent of offset/limit truncation"
  status_vocabulary: "closed 3-entry map, keyed by program_releases.type: 'Feature release'->dot #1f8a5b, 'Patch release'->dot #2a6fdb, 'Hotfix'->dot #d1495b. label is the type name verbatim. A type outside this set is a data-integrity error -- the service raises rather than emitting an unstyled row (FR-PGD03-3, DECISIONS.md D-03)"
  rbac: "program_visibility(current_user, program_id) (rbac-checks/AUTH-03) called once with the real program_id -- open-aggregate, any authenticated session, never denies and never filters by current_user.programs; byte-identical response across every persona (AC-4), matching program-detail-api/program-token-trend-api's convention"
  errors: "400 invalid_range if range is outside {7d,30d,90d}, via the shared validate_range() envelope; 404 program not found if program_id does not exist (matches program-detail-api's convention, unlike program-token-trend-api's no-404 exception); 401 if the bearer token is missing or invalid; 5xx if a program_releases row's type is outside the closed vocabulary (data-integrity error, not a 200 with an unstyled row)"
  index: "program_releases(program_id, date) compound index required for the NFR-002 <=2s budget at 5000+ releases/program -- added by migration 007 (DECISIONS.md D-04, promoted ADR-0015); the endpoint's row query and count query both filter WHERE program_id = :pid AND date >= :range_start"
```

### program-commands-api

```yaml
produced_by: PGD-04
consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01]
shape:
  endpoint: "GET /api/overview/program-detail/{program_id}/commands?range=7d|30d|90d (default 30d, via the shared _range_with_default wrapper around validate_range()) -- a fourth sibling on the existing overview router (prefix=/api/overview), not a separate program-detail router"
  response_model: "CommandsPanel @ app/schemas/personal_usage.py -- REUSED verbatim from SHP-02 (PGD-04/DECISIONS.md D-03); no schemas/program_commands.py exists"
  items: "list[CommandEntry { command: str, count: int, barStyle: str }], ordered by count DESC then command (deterministic tiebreak, matching SHP-02). command passes through usage_events.command VERBATIM -- real ingest data already carries the leading '/' (e.g. '/arh-init'); the API never synthesizes one. count is a RAW int (bar-formula input, deliberately not pre-formatted). barStyle is round(count / MAX(counts in this range and program) * 100)% width -- max-of-range, NOT share-of-total (PGD-04-FR-3, ADR-0009-inherited formula)."
  total_runs: "str, pre-formatted via format_number() -- sum of in-range command counts."
  data_source: "usage_events (per-event ts), filtered by program_id and the resolved range window -- NEVER program_commands (lifetime-only rollup with no time filter; PGD-04/DECISIONS.md D-01). This is the single highest-risk implementation detail: reading program_commands instead makes ?range= a silent no-op."
  empty_behavior: "Unknown OR known-but-quiet program_id both return 200 {total_runs: \"0\", items: []} -- NO program_summary existence lookup, NO 404 (PGD-04/DECISIONS.md D-02). Deliberately inconsistent with the sibling /releases route on the same router, which does 404; the inconsistency is principled, not an oversight -- see D-02."
  rbac: "program_visibility() open-aggregate veto gate (AUTH-03), called once with the real program_id; never filters by current_user.programs; byte-identical response across every persona."
  errors: "range outside {7d,30d,90d} -> HTTPException(400, 'invalid_range'); 401 if unauthenticated. No 404 (see empty_behavior)."
  independence: "Computed independently from personal-usage-api's commands panel (AC-6/FR-SH-15) -- both read usage_events but with different predicates (program_id vs user); neither derives from the other."
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
  endpoint: "GET /api/personal-usage/{user_id}?range=7d|30d|90d (default 30d, via a story-local _range_with_default wrapper around the shared validate_range())"
  response_model: "PersonalUsageResponse @ app/schemas/personal_usage.py (SHP-02/DECISIONS.md D-04, promoted ADR-0009)"
  cards: "list[PersonalUsageCard { glyph: str, value: str, label: str, iconBg: str, iconColor: str }], exactly 4 entries, order-locked: Sessions, Total time, Total tokens, Avg tokens/session — a TO-DATE aggregate over ALL of the user's sessions, NOT scoped to range. glyph/label/iconBg/iconColor are fixed presentation constants owned by the producer (mirrors program-detail-api's _SUMMARY_CARD_GLYPHS_LABELS precedent, extended to a 4-tuple). value: format_number() for Sessions/Total tokens/Avg tokens per session (api-conventions); format_duration() for Total time. No delta field ships — present in the mockup's mock-data generator, bound in zero templates."
  daily_tokens: "DailyTokenSeries { points: list[{date: str, value: str}], period_total: str, avg_per_day: str } — RANGE-scoped (7/30/90 points, zero-padded for a day with no sessions, oldest-to-newest). point.value/period_total/avg_per_day all pre-formatted via format_number() (FR-2's literal field names). Raw numeric series per overview-token-series-api's (OVW-02) precedent — no rendered chart markup; frontend chart-rendering approach is a separate, still-open decision (docs/requirements/RTM.md § Decisions 2026-09-07), not settled here."
  commands: "CommandsPanel { total_runs: str, items: list[{command: str, count: int, barStyle: str}] } — RANGE-scoped, computed from usage_events only (cards/daily_tokens come from user_sessions). total_runs pre-formatted via format_number(); count is a RAW int (the bar-formula input, deliberately not pre-formatted); barStyle is round(count / max(all in-range counts) * 100)% width, i.e. max-of-range — NOT count / total_run_count * 100 as the story AC3 prose literally reads (SHP-02-FR-3, resolved in the mockup's favour per CLAUDE.md § Design system)."
  scope: "no program_id anywhere in the request or response — cross-program aggregate by contract."
  rbac: "self-view gated by rbac-checks' individual_usage_visibility (self always; else cio only, FR-AUTH-07); a denial is a bare HTTPException(403) (no data body), logged individual_view_denied."
  errors: "range outside {7d,30d,90d} -> HTTPException(400, 'invalid_range') via the shared api-conventions envelope, identical to every other validate_range() consumer."
  authz_note: "SHP-02's own self-view calls this gated by rbac-checks' individual_usage_visibility (self always; else cio only, FR-AUTH-07). PGD-05 reuses this same endpoint/shape as the Project Team per-member drill-down popup — same contract, no new interface — gated instead by rbac-checks' member_in_program_visibility (program check AND (self OR cio), FR-AUTH-08); denials logged as member_view_denied, not individual_view_denied."
```

### session-identity-api

```yaml
produced_by: AUTH-07
consumed_by: [OVW-05, PGD-07]
shape:
  endpoint: "GET /api/me"
  purpose: "The ONE surface that answers 'who am I signed in as, and which dashboard view am I entitled to' -- there is no other today. Nothing in the shipped API returns the session's display name or its resolved persona (`/api/programs` returns programs, `/api/overview/*` returns cards/series, `/api/personal-usage/{user_id}` returns usage), which is exactly why `AdoptionOverview` omits `persona` entirely (OVW-01 D-04) and `PersonaDashboardShell`'s identity block never renders."
  response: "{ name: str | None, persona: str } -- two fields, deliberately. FILLED AT PLAN TIME (AUTH-07, docs/features/AUTH-07/PLAN.md T-07): `services/api/app/schemas/me.py::MeResponse`, a `pydantic.BaseModel` with `model_config = ConfigDict(extra=\"forbid\")` so no additional field can ever leak onto the wire, matching `AUTH-07-AC-1`'s exact-two-field assertion. Route `services/api/app/api/me.py::GET /api/me` mirrors `app/api/programs.py`'s dependency shape (`current_user: CurrentUser = Depends(get_current_user)`, `persona_resolver: PersonaResolver = Depends(get_persona_resolver)`); handler body is `MeResponse(name=current_user.name, persona=await persona_resolver.resolve(current_user.role))`, with `PersonaNotFoundError` caught before its own base class `PersonaResolutionError` (both -> `HTTPException(403)`), mirroring `app/api/programs.py:87-112`'s catch order. No route-owned cache: every call re-invokes `resolve()`, riding persona-resolver's own 300s TTL (AC-7)."
  name: "the signed-in user's display name for the brand bar's identity block (mockup values `Elena Vasquez` / `Devon Rao`). Read from the verified access token's OIDC profile claims -- `OIDC_SCOPE`'s shipped default already requests `profile`, so no realm/scope/mapper change is needed. Fallback chain: `name` -> `given_name` + ' ' + `family_name` -> `preferred_username` -> None. NEVER a fabricated placeholder and never composed from the email address: `None` is the honest answer, and the consumer already has a real rendered state for it (persona-shell `states.populated` / SHP-01 D-05's neutral 34x34 circle, no initials, aria-hidden). A `POST /auth/dev-bypass` token carries no profile claims at all, so `name` is None on that path by construction -- expected, not a defect."
  persona: "AUTH-02's `resolve(session.role)` output, verbatim. Typically one of `cio | architect | developer | product-manager | engineering-manager`, but no enum is pinned on the wire -- persona-resolver's own `output` field is data-driven and any ops-configured value returns as-is. Server-derived, never inferred by the caller from its own route: `/overview` is RBAC-gated to `cio` today, so the page COULD hardcode `persona: 'cio'`, and that is rejected on purpose (RTM Decisions 2026-09-10) -- the persona selects the avatar colour and the job-title literal the brand bar displays about the user, so a page-side constant would assert an identity the server never confirmed."
  excluded_fields: "no `jobTitle` (a frontend per-persona presentation constant, CONFIRMED by user 2026-09-10 -- see `persona-shell`'s `job_title_source_note`/`job_title_divergence_note`, and note the values are plain role names, not the mockup literals), and no `email`/`groups`/`programs`. No mockup binds any of them, and widening the session's exposure with no consumer is the opposite of what this seam is for. `session.programs` consumers read it server-side already (auth.md#session program_membership_source)."
  rbac: "authentication only -- there is no persona or membership gate, because the endpoint takes no target-user parameter and can only ever describe the caller. This is the structural difference from `personal-usage-api`, whose `/{user_id}` path is precisely what makes `individual_usage_visibility` necessary there; `/api/me` has no such surface to gate."
  errors: "401 (missing/invalid bearer) -> get_current_user's existing behaviour. 403 when persona resolution fails -- `PersonaNotFoundError`/`PersonaResolutionError` (persona-resolver) convert to HTTPException(403) exactly as rbac-checks already does, fail-closed; a 200 NEVER carries a null, defaulted, or guessed `persona`. Consumers render this as the shell's existing error state (persona-shell `states.error` -- the neutral 'Persona unavailable' badge plus its aria-live announcement, which SHP-01 built for exactly 'whatever sentinel the composing page passes after catching AUTH-02's PersonaNotFoundError'), so no new frontend state is invented for it."
  perf: "one call per page render; `resolve()` is already per-process cached 300s (persona-resolver `cache`). Not a list endpoint -- no pagination applies."
  under_declared_edge: "consumed_by lists TWO stories (`OVW-05`, `PGD-07`) -- `PGD-07` was added 2026-09-10 after the Program Detail brand bar was found to be missing the same identity block, which is also what lifted this contract off the one-consumer smell this schema warns about. Still knowingly incomplete: `ARC-01`/`DEV-01`/`PMD-01`/`EMD-01` each need the same `{name, persona}` pair to fill `persona-shell`'s `signedInUser`/`persona` props, and `persona-shell` already lists all four as consumers. They are `validated` rows this intake run is not permitted to edit, and adding them here without adding this contract to their own `Contract` column (plus `AUTH-07` to their `Depends-on`) would break the two-views-must-agree rule in the other direction. Recorded as DELIBERATELY ACCEPTED, not overlooked, per the `program-manifest-api` precedent (RTM Decisions 2026-09-08). Close it when one of those four is next touched."
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
consumed_by: [ING-04, ING-09]  # ING-06 removed 2026-09-15 (WONTFIX, RTM Decisions) -- see RTM Decisions 2026-09-15 for reasoning; historical references above may still name it
shape:
  endpoint: "POST /api/ingest/files"
  ing03_router_topology: >
    ADR-0013 — the shipped route is `POST /api/ingest/{kind}` with
    `kind='activity'` (i.e. the wire URL is `POST /api/ingest/activity`,
    not `POST /api/ingest/files`), a single generic handler on
    `app/api/ingest.py` (renamed from `ingest_files.py` in ING-03 T-04
    via `git mv`). The activity branch preserves ING-02 semantics
    byte-for-byte per ADR-0013 § Consequences: same request-tier order,
    same 413 row cap, same `background_tasks.add_task(dispatch_org_rebuild)`
    ADR-0012 scheduling. Envelope-kind vocabulary lives in
    `_ACCEPTED_KINDS = frozenset({'activity', 'artifacts'})` — ING-03
    T-01 extended it from ING-02's `{'activity'}`.
  auth: "ingest-token-auth bearer (ING-01, `services/api/app/core/ingest_auth.py`); envelope `program_id` must be in the token's `allowed_program_ids` (or wildcard `*`, or empty = allow-all — ING-01 semantics). Manual `await get_ingest_token(program_id=..., credentials=..., session=db)` because `program_id` lives in the body, not the path/query (FR-5 / C-4 — mirrors app/api/manifest.py verbatim). Never session-cookie."
  request_body: "raw JSON dict — envelope `{program_id: str, kind: 'activity', rows: list[ActivityRowIn]}`. Envelope-level Pydantic bind is deliberately NOT used (matches manifest.py precedent); envelope fields are checked off the raw dict, then per-row Pydantic validation runs in the service layer. Envelope `kind` vocabulary lives in `app/core/ingest_kind.py::_ACCEPTED_KINDS = {'activity'}` (FR-7 / C-6 — ING-03 extends this frozenset with 'artifacts')."
  limits: "5000 rows/request cap (AC-4). Router rejects `len(rows) > 5000` with 413 before any DB work; `activity_ingest._ENVELOPE_ROW_CAP = 5_000` in the service enforces the same limit defence-in-depth. Chunked upsert further limits per-INSERT rows to `_MAX_ROWS_PER_INSERT = 2_730 = floor(65_535 / 24 cols)` inside one transaction (FR-2 / C-1)."
  rows_shape:
    schema_module: "`services/api/app/schemas/ingest_files.py::ActivityRowIn` — Pydantic v2, `model_config = ConfigDict(populate_by_name=True, extra='ignore')`. Unknown row-level fields are silently dropped, the row still commits (FR-4 / Q-01, disposition C-2). `populate_by_name=True` lets tests/service construct rows using either the wire name or the column name."
    wire_aliases: >
      Five wire→column aliases (Q-01, resolved 2026-09-09) — the wire uses raw
      `activity.jsonl` field names, the API stores under `usage_events` column names:
        duration_s   -> duration_seconds
        input_token  -> input_tokens
        output_token -> output_tokens
        cache_read   -> cache_read_tokens
        cache_write  -> cache_write_tokens
    fields: |
      Every field on `ActivityRowIn` (verbatim from schema module, wire-name column first):
        program_id       str          required — must match envelope program_id (mismatch → rejection reason program_id_mismatch, service layer)
        ts               ISO-8601 str required — pre-parsed by field_validator(mode='before'); unparseable → reason malformed_iso_date
        cmd_ts           ISO-8601 str required — same parser as ts; part of idempotency key
        user             str          required — PII, never logged or embedded in RejectionEntry (FR-8 / C-7)
        session_id       str          required — part of idempotency key (program_id, session_id, cmd_ts)
        kind             str | null   optional — row-level kind, stored verbatim per Q-02, NO vocabulary check
        command          str          required
        feature          str | null   optional
        duration_s       int          required — wire alias for duration_seconds
        outcome          str          required
        intervention_count int | null optional
        files_created    int | null   optional
        files_modified   int | null   optional
        lines_added      int | null   optional
        tool_rejections  int | null   optional
        input_token      int | null   optional — wire alias for input_tokens
        output_token     int | null   optional — wire alias for output_tokens
        cache_read       int | null   optional — wire alias for cache_read_tokens
        cache_write      int | null   optional — wire alias for cache_write_tokens
        total            int          required — total tokens (input + output + cache)
        models           object | null optional — per-model token breakdown, stored as JSONB
        source           str | null   optional — producer id (e.g. 'harness-mcp-push'); STORED per additive migration 006 (FR-4)
        copilot_credits  decimal | null optional — per-row credits consumption; STORED per migration 006 (FR-4)
    unknown_field_policy: "extra='ignore' — unknown row-level fields silently dropped; the row still commits. This is the FR-4 / Q-01 disposition, verified by T-07 wire→column alias unit test and covered by T-14 mixed-row integration test."
    idempotency_key: "unique(program_id, session_id, cmd_ts) — matches `usage_events` schema (BED-01/db-schema). Chunked `pg_insert(...).on_conflict_do_update(index_elements=['program_id','session_id','cmd_ts'])` gives the caller idempotent replay: a second POST of the same batch yields `inserted=0, updated=<row_count>`, no new rows."
    intra_batch_dedup: "before upsert, rows are deduplicated in Python on (program_id, session_id, cmd_ts); last row wins on collision (matches ON CONFLICT DO UPDATE semantics). Dropped duplicates count into `rejected[]` with reason `intra_batch_duplicate` and the ORIGINAL row's index in the input array (FR-3 / C-2). Prevents CardinalityViolation on batches with the same key twice."
  response_shape:
    schema_module: "`services/api/app/schemas/ingest_files.py::IngestFilesResponse` — flat counts + rejection list + program-scope rollup summary. HTTP 200 on success (partial rejections DO NOT change the status — rejections ride in `rejected[]`)."
    fields: |
      received         int                    total rows in the request payload
      valid            int                    rows that passed validation AND intra-batch dedup
      inserted         int                    rows newly inserted into usage_events (ON CONFLICT DO UPDATE arm not taken)
      updated          int                    rows updated in place via ON CONFLICT DO UPDATE
      rejected         list[RejectionEntry]   per-row rejection outcomes — {index, reason} only
      rollup_summaries object                 program-scope RebuildResult from rebuild_program_rollups(); org-scope rebuild runs out-of-band (see rollup_summaries_scope)
    rejection_entry: "`RejectionEntry { index: int, reason: str }` — `index` is the row's position in the request's original `rows[]` array. `reason` is one of the codes below. NEVER carries row content (FR-8 / C-7 PII discipline) — no user/command/feature/ts/cmd_ts/session_id ever appears in a RejectionEntry."
    rejection_reasons: |
      Vocabulary the service layer emits (docs/features/ING-02/DATA-DESIGN.md § 3):
        malformed_iso_date       ts or cmd_ts failed ISO-8601 parse (schema module's field_validator raises this literal)
        missing_required_field   Pydantic's built-in `missing` error type — a required field was absent
        intra_batch_duplicate    row's (program_id, session_id, cmd_ts) collided with an earlier row in the same batch; last-wins, this row dropped
        program_id_mismatch      row-level program_id differs from the envelope program_id (service layer, not schema — the row model has no view of the envelope)
      Vocabulary is NOT constrained via Literal on RejectionEntry — a future ingest kind (ING-03 artifacts) may extend this list without a schema-module edit. Enforced by service + asserted by T-14 integration test.
    rollup_summaries_scope: "program-scope ONLY. `rebuild_program_rollups(session, program_id)` runs synchronously after commit and its `RebuildResult` populates this field. `rebuild_org_rollups(session)` runs OUT-OF-BAND via FastAPI `BackgroundTasks` (D-01 / ADR-0012 — supersedes AC-1's original 'run synchronously' wording) and reports through its own emitter; it is NEVER included in this response. Callers that need org-scope confirmation observe the async event, not this field."
  errors:
    "400": "envelope invalid — non-dict body, missing/non-string `program_id`, or envelope `kind` not in `_ACCEPTED_KINDS = {'activity'}` (FR-7 / AC-4 abort tier). Zero writes. Router-tier check, before auth."
    "401": "missing or invalid Bearer token — get_ingest_token's own behaviour (ING-01)"
    "403": "token's `allowed_program_ids` does not include the envelope `program_id` — get_ingest_token raises HTTPException(403); no data body"
    "404": "envelope `program_id` does not resolve to a known program — get_ingest_token behaviour when the program is unknown"
    "413": "len(rows) > 5000 — router rejects before DB work; zero writes (AC-4). `activity_ingest._ENVELOPE_ROW_CAP` mirrors the limit defence-in-depth"
  observability: "one structured log event per completed request — `event: 'ingest_write_completed'`, allowlist keys ONLY: {event, program_id, rows_received, rows_inserted, rows_updated, rows_rejected, duration_ms} (FR-8 / C-7). NEVER user, command, feature, session_id, cmd_ts, or any row content. Asserted by `test_ingest_pii_logging.py` (T-11) via allowlist diff, not denylist."
```

### program-manifest-api

```yaml
produced_by: ING-10
consumed_by: []          # write-only ingest endpoint, same shape as ingest-artifacts-api/admin-scan-api -- no story reads this endpoint directly. AUTH-06 depends on the TABLE this endpoint writes (program-roster-schema, data.md), not on this API contract (RTM Decisions 2026-09-08 "Contract correction"). ING-04/ING-06 are the likely missing MCP/CLI-caller edges -- CONFIRMED by user as deliberately DEFERRED, a knowingly under-declared edge accepted on purpose, not overlooked (RTM Decisions 2026-09-08).
shape:
  endpoint: "POST /api/ingest/manifest  {programId, program:{name,type,description}, team:[{email,name,role,aliases[]}]}"
  auth: "ingest-token-auth bearer; program_id must be in allowed_program_ids (or wildcard)"
  source_of_truth: "each program's own committed .harness/program.yaml -- NOT the OIDC groups claim (RTM Decisions 2026-09-08). Onboarding a program requires no Keycloak group or role."
  identity_write: "program:{name,type,description} upserts program_summary's descriptive columns. BED-03's rebuild_program_rollups() preserves these rather than blanking them, so a rollup rebuild after ingest keeps the header/label intact."
  roster_write: "team[] upserts program-roster-schema's program_roster table (data.md; program_id, email, name, role, source='file'), NOT program_members -- CONFIRMED by user: the source PRD's own wording ('upserts program_members') was wrong, verified against shipped code before asking (services/api/app/services/rollup_rebuild.py:360 delete(ProgramMembers), :370 _build_program_members() with no prior-state param, unlike program_summary's shipped prior_identity carry-forward) -- so a program_members upsert would be silently wiped by the next ING-02 ingest; no validated story (BED-03) reopens (RTM Decisions 2026-09-08). Also upserts user_roles (email PK, role, source='file') for the org-level role, unchanged. Each alias in aliases[] gets its OWN program_roster row -- usage joins on usage_events.user, which carries whatever `git config user.email` was set to on the producing machine, and session-membership matching (AUTH-06) checks session.email against every row's email column, primary or alias, equally."
  removal_semantics: "CONFIRMED by user: a full manifest re-push marks any program_roster row for that program_id whose email is no longer in team[]/aliases[] as removed_at=now() (soft-delete, never hard-deleted) -- see program-roster-schema (data.md) and RTM Decisions 2026-09-08"
  role_mapping: "short roster slugs (dev|arch|pm|em|cxo|board_member) map to long dashboard roles through ONE shared table. `admin` was REMOVED 2026-09-08 (DECISIONS.md D-10, flag AF-01): it used to fold onto `cio`, which bypasses program scoping entirely, and a roster slug comes from a program's own committed .harness/program.yaml -- so it let a program grant org-wide visibility from inside its own repo. `map_role_slug("admin")` now returns None and the entry becomes a row-level rejection. The Keycloak path made the same call in PR #235. Reason this stays ONE table, so the file writer and ING-08's Keycloak writer cannot drift. Scoped to ING-10 only in this pass (in-process mapping, single consumer) -- an author assumption the user accepted as-is, not a fresh confirmation; wiring ING-08 onto it remains an open, undecided scope change to a shipped story (RTM Decisions 2026-09-08)."
  harness_layout: "CONFIRMED by user: the reference two-file layout is canonical -- committed program.yaml (programId, program:, team[], files[], artifacts{}) + local/gitignored profile.yaml (email/name/role, a self-check never trusted by the dashboard). ING-10 accepts only this canonical shape on the wire. This repo's own .harness/profile.yaml is currently non-conforming (committed, holds files[]/artifacts{} with no program:/team[]) and must be migrated -- touches ING-06's dogfooding path (RTM Decisions 2026-09-08)."
  precedence: "file is authoritative for program membership/roles. Deliberately the OPPOSITE of the CIO Dashboard Project prior art (src/lib/identity/file-roles.ts), where Keycloak won and the file only filled gaps -- that predates the 2026-09-08 decision."
  program_type_enum: "Greenfield|Brownfield|Upgradation|Migration|Maintenance -- authoritative; apps/web/src/lib/programStyle.ts widens PROGRAM_TYPE_COLORS to cover it (folded AC, RTM Decisions 2026-09-08)"
  response: "received/valid/rejected counts per section (identity, roster), plus per-email created/updated/skipped and rejection reasons"
  ing08_boundary: "user_roles stays reference/audit on the session path (ING-08 AC-4 unchanged); program membership is read from program_roster, not user_roles and not program_members"
```

### ingest-artifacts-api

```yaml
produced_by: ING-03
consumed_by: [ING-04]
shape:
  endpoint: "POST /api/ingest/artifacts  {program_id, kind:'artifacts', counts, as_of}"
  router_topology: "ADR-0013 — the shipped route is `POST /api/ingest/{kind}`, a single generic handler on `app/api/ingest.py` (renamed from `ingest_files.py` in ING-03 T-04; the retired `POST /api/ingest/files` literal URL was replaced by `POST /api/ingest/activity` byte-for-byte). Envelope-kind vocabulary lives in `app/core/ingest_kind.py::_ACCEPTED_KINDS = frozenset({'activity', 'artifacts'})` — extended from ING-02's `{'activity'}` by ING-03 T-01. A path-param regex constraint would fork this vocabulary; see ADR-0013 § Consequences."
  auth: "ingest-token-auth bearer (ING-01, `services/api/app/core/ingest_auth.py`); envelope `program_id` must be in the token's `allowed_program_ids` (or wildcard `*`, or empty = allow-all — ING-01 semantics). Manual `await get_ingest_token(program_id=..., credentials=..., session=db)` because `program_id` lives in the body, not the path/query — mirrors `app/api/manifest.py` and the ingest-files-api activity branch verbatim. Never session-cookie."
  request_body: >
    Wire envelope `{program_id: str, kind: 'artifacts', counts: dict[str, int],
    as_of: ISO-8601 datetime}`. Bound to `ArtifactCountsIn`
    (`services/api/app/schemas/ingest_artifacts.py`) — Pydantic v2,
    `ConfigDict(extra='ignore', populate_by_name=True)`.
    Envelope-kind check (URL path `{kind}` + body `kind`, both against
    `_ACCEPTED_KINDS`) runs BEFORE bearer auth (FR-1) — the two MUST agree
    or the request is rejected 400 with `unknown envelope kind`.
  fields: |
    program_id  str          required — must match the token's `allowed_program_ids`
    kind        Literal['artifacts']  required — MUST equal 'artifacts'
    counts      dict[str,int] required — keys MUST be from the closed canonical vocabulary (see canonical_types); values are integer counts (>=0 by convention, no upper bound)
    as_of       ISO-8601 str required — the producer-reported observation timestamp, stored verbatim in `program_artifacts.as_of_timestamp`
  canonical_types: |
    Closed vocabulary — the five values in
    `app/schemas/ingest_artifacts.py::_CANONICAL_ARTIFACT_TYPES` (frozenset):
      prd
      user_story
      test_case
      arch_diagram
      api_spec
    Case-sensitive. A `counts` key outside this set (or the empty string)
    is rejected 400 at the schema tier with `unknown_canonical_type` in the
    validation-error detail. Vocabulary drift is prevented by
    `test_ingest_artifacts_schema.py`'s parametrised probe.
  idempotency: >
    `pg_insert(program_artifacts).values(rows).on_conflict_do_update(
    index_elements=['program_id','type'], set_={'count': excluded.count,
    'as_of_timestamp': excluded.as_of_timestamp})` inside `session.begin()`
    -> one `db.commit()`. A second POST of the same envelope yields the
    same `rows_upserted` count with no duplicate rows (FR-3 / AC-5 /
    DECISIONS.md D-02). At most 5 rows fit in one INSERT (the canonical
    type set has 5 entries), so no chunking; well under Postgres's 65_535
    bind-parameter limit.
  response_shape:
    schema_module: "`services/api/app/schemas/ingest_artifacts.py::IngestArtifactsResponse` — flat counts + rejections list. HTTP 200 on success. Symmetric with `IngestFilesResponse` (int + int + list[RejectionEntry]) per DECISIONS.md D-02 / Q-02."
    fields: |
      rows_received  int                   total (program_id, type) rows the envelope carried (== len(counts))
      rows_upserted  int                   rows persisted via ON CONFLICT DO UPDATE (insert OR update; not disambiguated because the wire caller has no legitimate use for the split)
      rejections     list[RejectionEntry]  per-row rejection outcomes — currently always [] on the happy path (schema-tier validation is all-or-nothing 400; there is no partial-batch rejection surface today). Present in the response envelope for shape symmetry with ingest-files-api and forward-compatibility with a future partial-batch mode.
    rejection_entry: "reuses `services/api/app/schemas/ingest_files.py::RejectionEntry { index: int, reason: str }` — same shape and same PII discipline (FR-5 / C-7) as the activity branch; row content NEVER appears."
    no_rollup_summary: >
      The response does NOT carry a `rollup_summaries` field.
      `program_artifacts` is a leaf counts table — no rollup source
      relationship (`app/services/rollup_rebuild.py` neither reads nor
      writes it). ADR-0012 is non-applicable on this branch
      (DECISIONS.md D-03): the service MUST NOT import
      `rebuild_program_rollups` or `rebuild_org_rollups`, and NO
      `BackgroundTasks.add_task(...)` fires from the artifacts dispatch
      branch. Enforced by
      `tests/unit/test_ingest_artifacts_no_rollup_dispatch.py`
      (F-16, static AST + signature guard).
  errors:
    "400": "envelope invalid — non-dict body, missing/non-string `program_id`, kind not in `_ACCEPTED_KINDS` (`unknown envelope kind`), URL path kind != body kind (`unknown envelope kind`), or `ArtifactCountsIn.model_validate` failed (`invalid artifacts envelope`; canonical-type violation, missing field, non-integer count). Zero writes. Router-tier check, before auth."
    "401": "missing or invalid Bearer token — `get_ingest_token`'s own behaviour (ING-01). Zero writes."
    "403": "token's `allowed_program_ids` does not include the envelope `program_id` — `get_ingest_token` raises HTTPException(403); zero writes."
    "404": "envelope `program_id` does not resolve to a known program — `get_ingest_token` behaviour when the program is unknown. Zero writes."
  observability: >
    One structured log event per completed write —
    `event: 'ingest_artifacts_write'`, allowlist keys ONLY:
    `{event, program_id, token_label, types_written}` (FR-5 / C-7).
    Allowlist is the module-level frozenset
    `app.services.ingest_artifacts._LOG_FIELD_ALLOWLIST`. NEVER
    `user_email`, `token_hash`, `as_of`, raw `counts` values, or any
    request-body field. Event name is intentionally distinct from
    ING-02's `ingest_write_completed` so dashboards can aggregate
    per-kind without payload-shape collision (`test_ingest_artifacts_observability.py`). PII allowlist enforced by
    `test_ingest_artifacts_pii_logging.py` (F-15) via allowlist diff,
    not denylist.
```

### mcp-tools

```yaml
produced_by: ING-04
consumed_by: [ING-05]
shape:
  server: >
    services/mcp-server/ — package `agentrise_mcp`, FastMCP v2.x streamable HTTP
    transport on 0.0.0.0:3010 path /mcp (FR-1, D-02). Standalone sibling to
    services/api, separately deployed (D-01, ADR-0014) — NOT wired into
    `docs/config/project-commands.yaml::preflight` (D-07). Smoke procedure
    lives in `docs/config/stack-smoke.md` under the `# mcp-server` section.
  auth: >
    Bearer token via env `AGENTRISE_INGEST_TOKEN` — enforced at MCP-server
    startup (fail-fast: missing/empty aborts before any HTTP or filesystem
    call, FR-6 / D-06) and re-applied as `Authorization: Bearer <token>` on
    every HTTP POST to `/api/ingest/*`. Same ingest-token-auth mechanism
    ingest-files-api / ingest-artifacts-api / program-manifest-api use
    (ADR-0006). Base URL overridable via `AGENTRISE_INGEST_BASE_URL`
    (default `http://127.0.0.1:8000`).
  tools:
    push_activity: |
      push_activity(program_id: str | None = None, workspace_root: str | None = None) -> dict
      Reads `.harness/program.yaml::files[]` glob patterns (D-04).
      Parses each matched file as NDJSON, batches at 500 rows per POST (D-05).
      POSTs to `POST /api/ingest/activity` per ADR-0013 — envelope
      `{program_id, kind:"activity", rows[]}`, kind literal `"activity"`.
      When `program_id` is supplied, overrides the YAML `programId` in the
      envelope (FR-1); when None, the YAML value is used.
      Backend response is `IngestFilesResponse`
      (`{received, valid, inserted, updated, rejected, rollup_summaries}`);
      the tool aggregates `inserted` / `updated` across batches, concatenates
      `rejected`, and merges `rollup_summaries` into `rollups` (last-write-wins).
      Result envelope on success (FR-2):
        {success: true, files_read, rows_read, batches, inserted, updated, rejected, rollups}
      Result envelope on auth failure (FR-5, 401 or 403):
        {success: false, error: "unauthorized" | "forbidden", http_status: 401 | 403,
         batches_sent, batches_failed, files_read, rows_read, inserted, updated,
         rejected, rollups}
      Result envelope on missing token (FR-6):
        {success: false, error: "missing_ingest_token",
         message: "Set AGENTRISE_INGEST_TOKEN before invoking this tool."}
      See FR-2, FR-5, FR-6.
    push_artifacts: |
      push_artifacts(program_id: str | None = None, workspace_root: str | None = None) -> dict
      Reads `.harness/program.yaml::artifacts{}` — the 5 canonical types
      (`prd`, `user_story`, `test_case`, `arch_diagram`, `api_spec`).
      Missing keys are OK (partial payload).
      Each type is resolved via its source `kind`:
        constant | glob-count | json-key-count | json-field-sum.
      When `program_id` is supplied, overrides the YAML `programId` in the
      envelope (FR-1); when None, the YAML value is used.
      POSTs once to `POST /api/ingest/artifacts` per ADR-0013 — envelope
      `{program_id, kind:"artifacts", counts, as_of}`, kind literal
      `"artifacts"`.
      Result envelope on success:
        {success: true, rows_received, rows_upserted, rejections, resolver_errors?}
      Result envelope on auth failure (FR-5, 401 or 403):
        {success: false, error: "unauthorized" | "forbidden", http_status: 401 | 403,
         batches_sent: 1, batches_failed: 1, inserted: 0}
      Result envelope on missing token (FR-6):
        {success: false, error: "missing_ingest_token",
         message: "Set AGENTRISE_INGEST_TOKEN before invoking this tool."}
      Result envelope on allowlist rejection (FR-7 / FR-8) — POST is aborted:
        {success: false, error: "unsafe_glob_pattern" | "unsafe_json_key",
         entry_key: "<canonical_type>", offending_value: "<value>"}
      See FR-3, FR-5, FR-6, FR-7, FR-8.
  timeout_retry: >
    5s connect + 30s total per HTTP call; 3 attempts with exponential backoff
    + jitter. Retry ONLY on network errors (connect/read/timeout) — NEVER on
    a 4xx or 5xx response, which are terminal and returned to the caller
    verbatim in the failure envelope (NFR-Performance).
  security: >
    Allowlisted event names in structured logs; `TokenSuppressionFilter`
    redacts token substrings and secret-keyed fields from every log record
    before it leaves the process (NFR-Security, R-07). Neither
    `AGENTRISE_INGEST_TOKEN` nor any bearer header ever appears in a log
    line, an error envelope, or an exception message.
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
