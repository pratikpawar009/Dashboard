# AgentRise Harness (Python Backend Edition) — AI Adoption & Governance Platform — Product Requirements Document

| Field | Value |
|-------|-------|
| Version | 1.0 |
| Date | 2026-08-26 |
| Author | Claude Code (derived from `docs/prd/agentrise-harness-adoption-platform.md` v2.0, commissioned by Pratik Pawar, pratik.pawar@apexon.com) |
| Status | Draft |
| Confidentiality | Internal |
| Document ID | PRD-agentrise-harness-python-backend-platform |

**Approvers**

| Name | Role | Signature | Date |
|------|------|-----------|------|
| {TBD} | Product Owner | | |
| {TBD} | Engineering Lead | | |
| {TBD} | Design Lead | | |
| {TBD} | Legal / Compliance | | |

**Revision History**

| Version | Date | Author | Summary of Changes |
|---------|------|--------|--------------------|
| 1.0 | 2026-08-26 | Claude Code | New project, derived from `docs/prd/agentrise-harness-adoption-platform.md` v2.0 (the as-built Next.js reference). **Product behavior is unchanged** — every FR/NFR/persona/journey below is the same system, same UI, same data contracts. What changed: the backend (API, RBAC, ingestion, data access) is re-specified for **FastAPI + SQLAlchemy/Alembic + Authlib**, replacing Next.js Route Handlers + Prisma + NextAuth. The frontend stays Next.js/TypeScript/recharts, now as a pure API client of the Python backend instead of hosting its own server-side data layer. FR/NFR IDs are kept identical to the reference PRD so the two documents cross-reference cleanly. See §B for the full technology mapping. |

---

## Executive Summary

AgentRise Harness is an internal, read-mostly analytics platform that answers one question for five different audiences: *how much is the org actually using AI-assisted software delivery, and is it being used safely?* This edition targets a **two-service architecture**: a **FastAPI (Python) backend** owns authentication (Keycloak OIDC via Authlib), RBAC, the Postgres data layer (SQLAlchemy/Alembic), and the ingestion pipeline; a **Next.js/TypeScript frontend** renders the five persona dashboards (CIO, Architect, Developer, Product Manager, Engineering Manager) as a pure REST client of that backend, reusing the same component/chart library (recharts) and page structure as the reference implementation so the UI is behaviorally identical. Data still flows the same way: a local Python **MCP server** (`services/mcp-server`, unchanged — it's already Python) exposes `push_activity`/`push_artifacts` tools that ship developer activity and artifact counts to bearer-token-authenticated ingest endpoints, which upsert a raw `usage_events` ledger and synchronously rebuild every downstream rollup table the dashboards read. Because the main backend is now Python too, it sits naturally alongside the MCP server in the same language and toolchain — a consistency the original Next.js-based system didn't have.

---

## 1. Problem Statement

*(Unchanged from the reference PRD — this is a product problem, not an implementation one.)*

### 1.1 Current Situation

Engineering leadership and individual contributors generate a large amount of AI-assisted-delivery signal every day — Claude Code / Copilot command invocations, tokens consumed, files touched, sessions run, artifacts produced (PRDs, stories, test cases, diagrams, API specs) — but that signal was scattered across local per-developer JSONL journals (VS Code workspace storage, Claude Code session logs) with no central store, no rollups, and no reporting surface. Nobody — not the CIO, not an Engineering Manager, not the developer who ran the command — had a single place to see it.

### 1.2 Root Cause

The AI tooling (Claude Code slash-commands, the `/arh-*` harness pipeline, VS Code Copilot Chat) was built to get delivery work done, not to report on itself. Its own logs are an incidental byproduct, written to whatever local file each client happens to use, in incompatible shapes, with no shared identity for a "usage event," no server to receive it, and no aggregation logic to turn ten thousand raw command invocations into a chart a CIO could look at in five seconds.

### 1.3 Business Impact

Without a central ledger and rollup layer, leadership cannot see program-level or org-level adoption trends, cannot correlate token spend with delivery output (releases, features, LOC), and cannot verify that governance guardrails (PII redaction, secret scanning, review gates) are actually enforced per program. Engineering Managers cannot coach adoption they cannot see. Architects and Product Managers cannot confirm artifact output or constitution compliance for their programs. The AI-tooling investment risks going unmeasured and, eventually, unjustified.

### 1.4 Evidence & Data Points

This PRD's evidence base is the reference implementation itself (`docs/prd/agentrise-harness-adoption-platform.md` §1.4), since this edition has not been built yet. This edition's job is to reproduce that same behavior, at the same fixture shape and scale, on a Python backend:

- The reference implementation's seed fixtures establish a realistic org shape: 9 programs, 6 already using AI SDLC tooling (67% adoption), 328.8M tokens consumed to date, 1,234,567 lines of code generated, 42 Harness releases, 18/{total} repos with Harness installed, ~120 synthetic sessions per (user, program) pair over a 90-day window, 12 months of monthly token/MAU series, 90 days of daily program-token series, 7 guardrail templates per program, and 4 org-wide constitution categories. This project's own seed CLI (`backend/app/cli/seed.py` + a Python fixtures module, per Appendix B) should reproduce this shape identically.
- The reference implementation **dogfoods its own pipeline**: `docs/activity/activity.jsonl` (plus a rolled-over `docs/activity/2026-07.jsonl`) contains real `/arh-*` command-activity records captured by the Copilot/Claude Code hooks during that project's own development, ingestible into a real `harness-self` program (`PROGRAM_ID = "harness-self"`, name "AgentRise Harness"). This edition should establish the same dogfooding pattern against its own build activity once scaffolded (see §13.2 Alpha phase).
- The reference implementation's `docs/state/features.json` (schema v3, see `docs/state/SCHEMA.md`) currently tracks 28 feature IDs across the two-tier state machine (OVW-01/02, PGD-01..05, BED-01..05, SHP-01..13, DEV-01/02, ARC-01, PMD-01, EMD-01), most already past the implementation phase — this edition's own state machine starts fresh and should track the equivalent feature set as it is decomposed from this PRD.

---

## 2. Goals & Non-Goals

### 2.1 Business Goals

*(Identical to the reference PRD §2.1 — unchanged by the backend language.)*

| Goal | Metric | Target | Timeline |
|------|--------|--------|----------|
| Give executive sponsors visibility to justify continued AI-tooling investment | Program adoption % (programs with ≥1 repo Harness-installed / total programs) | 100% (9/9 programs) | {TBD} |
| Track AI usage intensity/cost as a proxy metric for investment decisions | Organization-wide token consumption trend (monthly), computed from `usage_events` roll-ups, not estimates | Directional (trend visibility, not a fixed target) | Ongoing |
| Give managers/architects the same data to coach adoption and confirm guardrails are enforced | Guardrail pass rate per program | No unaddressed `NotImplemented` guardrail gaps | Ongoing |
| Make the platform self-service to extend: any developer can push their own activity without a central data-engineering dependency | Time from "developer mints an ingest token" to "their activity appears on their persona dashboard" (mint token → configure MCP env → run `push_activity`) | < 5 minutes | Target for this build |

### 2.2 Product Goals

- Provide the CIO a single landing page (Adoption Overview) with org-wide adoption %, token/MAU trends, and a drillable program board covering all programs.
- Provide a Program Detail drill-down with token trends, releases, command activity, project-team contribution, and per-member session time, shared byte-for-byte between the CIO and Engineering Manager views.
- Provide role-tailored dashboards for Architect, Developer, Product Manager, and Engineering Manager built from a shared component library.
- Provide a self-service, bearer-token-authenticated ingestion pipeline (MCP tools + hooks + CLI) so activity and artifact data flows in without a human re-typing it.
- Enforce role-based access with two distinct trust tiers: open-aggregate program data for any signed-in user, and gated individual/governance data.
- Serve all of the above through a FastAPI backend and a SQLAlchemy data model supporting 7D/30D/90D range filtering, pagination, and server-side computation of derived metrics (adoption %, deltas, averages, guardrail pass counts).

### 2.3 Non-Goals (This Version)

> Deliberate exclusions. Moving any item into scope requires a formal change request.

- **No browser-based creation/editing UI for any persona.** The frontend is entirely read-only. The only write paths are the bearer-token-authenticated machine ingest endpoints and the admin repo-scan endpoint — none reachable from the browser UI, none accepting session-cookie auth.
- **User administration and provisioning** — handled by Keycloak/the IdP; a role-sync script mirrors assignments for reference only.
- **Configuration or enforcement of the underlying AI tooling/guardrails** — the dashboard reports guardrail status; it does not run the checks.
- **PDF/CSV export of any view.**
- **Automated/scheduled ingestion** — ingestion is manually triggered (CLI or MCP push) in this version, same as the reference implementation; see FR-ING-11 (Could Have) for the deferred scheduler.
- **Rewriting the frontend framework.** The frontend stays Next.js/TypeScript/recharts — this PRD only changes the backend. A frontend-framework change is explicitly out of scope for this build.

### 2.4 Assumptions

| # | Assumption | Risk if Wrong | Affects Sections |
|---|------------|---------------|-----------------|
| A-001 | A Keycloak (or OIDC-compatible) IdP is reachable and configured, issuing a `role` claim plus `groups` claims prefixed `program-<slug>`. | Auth falls back to a dev-bypass-only mode; production auth is blocked until an IdP is wired. | §8.2, §9.1 |
| A-002 | `usage_events` is the single source of truth for every rollup table; rollups are always fully rebuilt, never incrementally patched — same invariant as the reference implementation. | Rollups and raw events can silently diverge with no reconciliation check. | §8.4, §6 (Ingestion FRs) |
| A-003 | Ingest tokens fully govern write scope for MCP/CLI/CI ingestion; a token minted with `"*"` can write to any current or future program. | Overly broad tokens become a wide blast radius if leaked. | §9 (Security) |
| A-004 | The "open aggregate" RBAC model (any authenticated user can view any program's aggregate data) is reproduced intentionally from the reference implementation, not accidentally. | If this assumption is wrong for this build, tighten the equivalent of `canViewProgram` to membership-scoping before launch. | §9.1, §6 (RBAC FRs) |
| A-005 | Program-membership group claims (`program-<slug>`) are the sole source of truth for the `/api/programs` list-scoping and the "Switch program" selector; there is no separate program-membership table. | If membership data needs to live outside the IdP (e.g., a manually maintained table), `/api/programs` scoping and the EM "Switch program" selector need rework. | §8.2, §6 |
| A-006 | The FastAPI backend can own the full OIDC session lifecycle and set a cookie the Next.js frontend can rely on without CORS complexity (same-origin via reverse-proxy path routing, `/api/*` → FastAPI). | If the frontend and backend must be deployed on genuinely separate origins with no shared proxy, the auth bridging design in §9.1 needs rework (token-based bridging instead of a shared cookie). | §8.1, §9.1 |

---

## 3. Stakeholders & Users

*(Unchanged from the reference PRD §3 — personas are a product concept, not a stack concept.)*

### 3.1 Stakeholder Map

| Stakeholder | Role | Interest / Concern | Involvement |
|-------------|------|-------------------|-------------|
| {TBD} | Product Owner | Overall product direction, scope, and prioritization | Approver |
| {TBD} | Engineering Lead | Technical feasibility, architecture, delivery quality | Approver |
| CIO / CXO | Executive Sponsor | Org-wide adoption visibility and investment justification | Consulted |
| Architects | Platform / Governance | Tool and model adoption, guardrail enforcement across programs | Consulted |
| Engineering Managers | Team Management | Team-level usage trends, coaching, capacity planning | Consulted |
| Product Managers | Product Area Ownership | Adoption trends per product area, prioritizing AI-enablement work | Consulted |
| Developers | Individual Contributor | Visibility into their own usage/impact; also the primary user of the MCP ingestion tools | Informed + direct tool user |
| Platform/DevEx (implicit) | Owner of the MCP server, ingest hooks, seed/sync scripts | Keeping the ingestion pipeline correct, idempotent, and low-friction for developers | Consulted |

### 3.2 Primary Persona

| Attribute | Detail |
|-----------|--------|
| Role | CIO / CXO |
| Context | Signs in via Keycloak SSO and lands on the Adoption Overview as the default landing page; returns to it regularly to check org-wide AI adoption health. |
| Primary Goal | Get an at-a-glance view of org-wide AI adoption, token spend, and delivery output, with the ability to drill into any program for trend context. |
| Pain Points | No consolidated org-wide view of adoption, token spend, or governance status across all programs; raw signal was scattered in local developer log files, not even in a database. |
| Success Looks Like | All programs visible on the board with accurate, backend-computed adoption %, clear trend charts, and confidence to make a decision without asking engineering for a custom report. |
| Tech Comfort | Medium |
| Frequency of Use | Weekly, with ad-hoc drill-downs |

### 3.3 Secondary Users

| Role | Key Need |
|------|----------|
| Architect | Personal AI usage plus program artifacts, releases, team contribution, governance/guardrail status, and the Organization Constitution. Governance-eligible. |
| Developer | Personal AI activity, commands, and session usage plus program contribution; the direct operator of the ingestion CLI/MCP tools. Governance-eligible (full-fidelity dashboard). |
| Product Manager | Mirrors the Architect view. Governance-eligible. |
| Engineering Manager | Program-level team view equivalent to the CIO's Program Detail page (byte-identical data), with a "Switch Program" selector limited to their own programs. **Not** governance-eligible. |

### 3.4 Anti-Personas

- **External customers / partners** — internal-only reporting tool.
- **Unauthenticated or unmapped-role users** — persona resolution throws when a role has no mapping in any configured source; such a user cannot reach any dashboard.
- **CI/automation identities acting as "users"** — CI and MCP clients authenticate with bearer ingest tokens against the ingest endpoints only; they never go through OIDC/Keycloak and never see a dashboard page.

---

## 4. Solution Overview

### 4.1 Solution Summary

AgentRise Harness (Python Backend Edition) splits into two cooperating services behind one logical origin. The **FastAPI backend** (`backend/`, Python 3.12) owns Keycloak OIDC authentication, RBAC, the Postgres data layer (SQLAlchemy 2.0 async + Alembic migrations), and the ingestion API. The **Next.js frontend** (`frontend/`, TypeScript, unchanged component/chart library) renders the five persona dashboards purely as an API client — no server-side database access, no NextAuth, no Prisma. A reverse-proxy layer (or Next.js `rewrites()` in dev) routes `/api/*` to FastAPI and everything else to Next.js, so the two feel like one origin to the browser and the session cookie FastAPI sets works without CORS friction. The **MCP server** (`services/mcp-server`) is carried over unchanged from the reference implementation — it already speaks Python/FastMCP, and now shares a language (and potentially shared Pydantic models) with the main backend for the first time.

### 4.2 Core Capabilities

| # | Capability | Priority (MoSCoW) | Version | Status |
|---|-----------|------------------|---------|--------|
| C-001 | CIO Adoption Overview — org summary cards, token/MAU trend charts, adoption-level indicator, program board | Must Have | v1.0 | Not started (new build; implemented in the reference implementation as OVW-01/02) |
| C-002 | CIO Program Detail — drill-down summary cards, daily token trend, releases, commands, project team, session time | Must Have | v1.0 | Not started (new build; mid-implementation in the reference implementation as PGD-01..05) |
| C-003 | Shared persona components (usage cards, daily charts, commands, session-wise usage, program summary, artifacts, releases, project team, compliance & guardrails, Organization Constitution) | Must Have | v1.0 | Not started (new build; implemented in the reference implementation as SHP-01..12) |
| C-004 | Architect Dashboard | Must Have | v1.0 | Not started (new build; implemented in the reference implementation) |
| C-005 | FastAPI backend + SQLAlchemy data model with RBAC enforcement | Must Have | v1.0 | Not started (new build — this is the edition-specific rework) |
| C-006 | Product Manager Dashboard | Should Have | v1.0 | Not started (new build; implemented in the reference implementation) |
| C-007 | Developer Dashboard (full-fidelity, governance panels included) | Should Have | v1.0 | Not started (new build; implemented in the reference implementation) |
| C-008 | Engineering Manager Dashboard (program-level team view + switch program) | Should Have | v1.0 | Not started (new build; implemented in the reference implementation) |
| C-009 | **MCP Activity & Artifact Ingestion Pipeline** — local MCP server, ingest-token minting/auth, bearer-authenticated ingest API, deterministic rollup rebuild, activity hook bridge, manual CLI ingester | Must Have | v1.0 | Carried over unchanged from the reference implementation (MCP server + hooks); ingest API re-implemented in FastAPI, not started |
| C-010 | GitHub org repo-scan for `reposWithHarnessInstalled` | Should Have | v1.0 | Not started (new build; implemented in the reference implementation) |
| C-011 | Config-driven persona resolution + program-membership scoping via IdP group claims | Must Have | v1.0 | Not started (new build; implemented in the reference implementation as BED-05, ADR-0003) |

### 4.3 Key Value Proposition

> For the CIO/CXO and the org's engineering leadership, **AgentRise Harness** is the reporting layer that turns raw, per-developer AI-tool log files into a single, role-tailored, trustworthy, self-service view of adoption, cost, delivery, and governance — now on a backend that shares its language and tooling with the ingestion pipeline that feeds it, reducing the number of ecosystems a platform engineer needs to hold in their head.

### 4.4 Solution Alternatives Considered

| Alternative | Why Not Chosen |
|-------------|---------------|
| Continue with ad-hoc log inspection / manual reporting | Does not scale, is not self-service, produces inconsistent figures across requesters — same product-level reasoning as the reference implementation. |
| Adopt a generic off-the-shelf BI tool pointed at raw log files | Would require significant custom modeling for personas, RBAC, guardrails/constitution, and — critically — a raw-event ingestion contract; also a new third-party dependency. |
| Build a single, unified dashboard for all personas (no role tailoring) | Would either overwhelm individual-contributor personas with org-wide detail or under-serve the CIO with drill-down depth. |
| Push activity from the CI pipeline only, no local developer tool | Loses per-developer session/duration fidelity (local Claude Code/Copilot journals capture things CI never sees, e.g. intervention counts, tool rejections, files touched mid-session); the MCP tool exists specifically to keep that local fidelity while still centralizing the data. |
| Django instead of FastAPI | More batteries-included (admin, ORM, auth) but heavier and more sync-oriented; doesn't match the async, Pydantic-schema-first style already established by the MCP server. |
| Full-Python frontend (Streamlit/Dash/Reflex) | Rejected for this build — the explicit goal is "same UI," and these frameworks would require rebuilding the recharts-based, multi-page, RBAC-gated dashboard UX from scratch with a different interaction model. |
| Keep the whole stack on Next.js (no change) | This is the reference implementation (`docs/prd/agentrise-harness-adoption-platform.md`); this document exists because a Python backend was explicitly requested. |
| Separate origins with token-based auth bridging (no shared proxy) | More portable across deploy topologies but adds token-refresh complexity to the frontend for no product benefit in an internal-tool context; deferred unless A-006 is invalidated. |

---

## 5. User Journeys

*(Identical to the reference PRD §5 in behavior; system-response language updated to name the FastAPI backend instead of Next.js Route Handlers.)*

### 5.1 Primary Journey: CIO Reviews Org-Wide AI Adoption and Drills into a Program

**Preconditions:** The CIO/CXO has a Keycloak account whose `role` claim maps to the `cio` persona, and has been granted access.

| Step | Actor | Action | System Response |
|------|-------|--------|----------------|
| 1 | CIO | Signs in via the frontend's sign-in page → Keycloak. | FastAPI completes the OIDC callback, resolves the persona from the `role`/`groups` claims, and sets a session cookie the frontend sends on every subsequent API call. |
| 2 | CIO | Lands on `/` (Adoption Overview). | Frontend calls `GET /api/overview/summary`, `/token-series`, `/mau-series`, `/program-board` on the FastAPI backend (org-access check enforced server-side); renders summary cards, 12-month token bar chart, 12-month MAU-by-role stacked chart, adoption indicator. `dashboard_login` event logged by the backend. |
| 3 | CIO | Scans summary cards and trend charts. | Backend-computed totals plus period-over-period deltas; the latest bar visually emphasized. |
| 4 | CIO | Scans the program board. | Program cards sourced from `GET /api/overview/program-board`, ordered by token consumption descending, each with an SVG sparkline. |
| 5 | CIO | Clicks a program card. | Frontend navigates to the program-detail route; `program_drilldown` event logged. |
| 6 | CIO | Reviews Program Detail. | Open-aggregate RBAC check passes; frontend renders header, 7 summary cards, daily token chart (default 30d, 7D/30D/90D toggle), releases, commands, team table, session-time chart — all from `GET /api/overview/program-detail/{program_id}`. |
| 7 | CIO | Uses "Switch program" or "← Back to program board." | Frontend reloads detail data for the new program id, or returns to `/`; `program_switch` logged. |
| 8 | CIO | Uses the data to make an investment or coaching decision. | — |

**Outcome:** The CIO has an accurate, current, org-wide picture of AI adoption and can substantiate a decision without requesting a custom report.

### 5.2 Secondary Journeys

- **Architect / Product Manager reviewing personal usage and program governance:** Signs in, lands on their persona dashboard, reviews "Your usage" cards, daily token/session charts, and personal command activity, then reviews program artifacts, releases, team, and the Compliance & Guardrails panel (governance check passes for this persona); opens the Organization Constitution panel and follows a deep link out to the governance system of record.
- **Developer reviewing personal contribution:** Signs in, lands on the Developer dashboard, reviews personal usage cards, daily token/session charts, commands, and paginated session-wise usage, then reviews the program summary, artifacts, governance panels (full-fidelity per the reference implementation's DEV-02 decision), releases, and project team.
- **Engineering Manager coaching a team:** Signs in, lands on the program-level team view for their default program, reviews team contribution and session time by member, clicks a team member's row to open the per-member popup (self-or-CIO-only gate), then uses "Switch program" (scoped to their own group claims) to review a different program.
- **Developer pushing local AI activity into the platform (MCP flow — unchanged from the reference implementation):** Developer mints an ingest token via the backend's token-minting CLI, stores it in the local MCP env file. Starts the backend and, separately, the local MCP server. Claude Code (or the Copilot activity hook bridge) invokes the `push_activity` tool, which reads local activity JSONL, batches rows, and POSTs to `POST /api/ingest/files` with the bearer token. The backend validates rows, upserts `usage_events`, and synchronously rebuilds program and org rollups. The developer's activity is visible on their dashboard on next page load.

### 5.3 Edge & Error Paths

*(Identical behavior to the reference PRD §5.3 — HTTP status codes and gating logic unchanged, only "route handler" language becomes "FastAPI endpoint.")*

| Scenario | Trigger | System Response | Recovery Path |
|----------|---------|-----------------|--------------|
| Unauthorized governance access | A CIO or Engineering Manager requests a governance endpoint (artifacts/constitution/guardrails). | Governance check denies; 403 with no data body. | UI omits the governance panels for those personas by design. |
| Unauthorized individual-detail access | A non-self, non-CIO user requests another user's personal-usage endpoint. | Denied, logged as an individual-view denial. | UI does not offer the popup affordance to unauthorized viewers. |
| Program not found | `program_id` doesn't exist. | 404 **after** the RBAC check passes (a denied request never leaks whether the program exists). | Not-found component renders; no metadata disclosure. |
| Invalid range parameter | `range` query param is not `7d`/`30d`/`90d`. | 400, via an explicit check — not FastAPI's default 422 (see FR-BE-02). | Range toggles are closed-set UI controls; should not occur from normal use. |
| Ingest token invalid/revoked/expired | Bearer token hash not found, or revoked, or expired. | 401. | Developer re-mints a token. |
| Ingest write outside token's program scope | Target program not in the token's allowed set and no wildcard present. | 403. | Token owner requests a broader-scoped token, or targets an authorized program. |
| Ingest payload too large | Row count exceeds the per-request cap (5000). | 413. | MCP client already batches at 500/request. |
| Malformed activity rows | A row fails schema validation (bad ISO date, missing required field, unrecognized kind). | Row dropped into the `rejected` bucket; response includes count + reasons. Valid rows in the same batch still commit. | Fix the source journal/hook and re-push; upserts are idempotent. |
| No freshness record (fresh DB, never ingested) | No system-metadata row for the ingestion key. | Backend raises a clear "ingestion job may not have run yet" error. | Seed or run a real ingest to populate the row. |
| Session expiry | OIDC session cookie expires while viewing a dashboard. | Frontend redirects to the Keycloak login flow. | User re-authenticates and is returned to the page they were viewing. |
| No data for selected range | 7D/30D/90D range with no underlying rows. | Chart/list renders a graceful empty state. | User widens the range or returns later. |

---

## 6. Functional Requirements

> Prioritized using MoSCoW. FR/NFR IDs are kept identical to `docs/prd/agentrise-harness-adoption-platform.md` §6 for cross-document traceability. Only the **Source** column and any implementation-noun references change; requirement text and acceptance criteria are otherwise the same behavior on a new backend.

### 6.1 Must Have — Launch Blockers

**Authentication & RBAC**

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-AUTH-01 | Authenticate via a Keycloak OIDC client registered only when the OIDC client id/secret/issuer settings are all configured. | Provider absent (auth routes 501/disabled) when any of the three settings is missing. | `backend/app/core/config.py`, `backend/app/auth/oidc.py` (Authlib) |
| FR-AUTH-02 | Provide a dev-bypass auth dependency (FastAPI dependency override) active only when `ENVIRONMENT != "production"`, accepting a role/email/programs override for local dev sign-in without a live IdP. | Dependency override is compiled out / raises in a production build. | `backend/app/auth/dev_bypass.py` |
| FR-AUTH-03 | Resolve a persona from the session's `role` via a three-tier, cached resolver: env var (JSON) → config file → Postgres `persona_config` table; 5-minute cache; raise if all three sources are empty for a given role. | Adding a new role→persona mapping via any one of the three sources (no code change, no deploy) takes effect within 5 minutes. | `backend/app/core/persona_resolver.py` |
| FR-AUTH-04 | Parse IdP group claims prefixed by a configurable program-group prefix (default `"program-"`) into the session's program-membership list on every sign-in. | A user in IdP group `program-alpha` has `"alpha"` in their session's program list. | `backend/app/auth/oidc.py` |
| FR-AUTH-05 | An org-access check authorizes only the `cio` persona for org-wide endpoints (`/api/overview/*`); logs the check outcome. | Non-CIO personas receive 403 from every `/api/overview/*` route. | `backend/app/core/rbac.py` |
| FR-AUTH-06 | A program-visibility check implements an **open-aggregate model**: any authenticated session may view any program's aggregate data; the program id argument is not used for gating (reproduced intentionally from the reference implementation, per A-004). | Any signed-in user, regardless of program membership, can load any program's detail data. | `backend/app/core/rbac.py` |
| FR-AUTH-07 | An individual-usage-visibility check allows self always; otherwise only the `cio` persona; logs denials. | A developer can view only their own personal-usage endpoint; a CIO can view anyone's. | `backend/app/core/rbac.py` |
| FR-AUTH-08 | A member-in-program-visibility check requires the program check AND (self OR `cio`); logs denials. | The Project Team per-member popup is reachable only under these conditions. | `backend/app/core/rbac.py` |
| FR-AUTH-09 | A governance-visibility check allows only `architect`, `product-manager`, `developer` personas (CIO and Engineering Manager explicitly excluded); when a program id is given, also requires the program check. | Governance endpoints all 403 for `cio` and `engineering-manager` sessions. | `backend/app/core/rbac.py` |
| FR-AUTH-10 | `GET /api/programs` scopes the returned list by persona: CIO sees all programs; every other persona sees only programs matching their session's program list. | A non-CIO "Switch program" selector never lists a program the user isn't a member of. | `backend/app/routers/programs.py` |
| FR-AUTH-11 | Dev-bypass paths skip both auth and RBAC entirely when active, and never emit audit-log events. | Dev-bypass is unreachable in a production build; audit logs show zero events for dev-bypass traffic. | `backend/app/auth/dev_bypass.py` |

**CIO Adoption Overview**

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-OV-01 | Display organization-wide summary cards: programs using AI SDLC (X/Y with adoption %), total token consumption, lines of code generated, releases using Harness, repos with Harness installed. | Cards render backend-sourced values from `GET /api/overview/summary` (`org_summary_rollup`, singleton row `org_id: "org-1"`), with a graceful all-zero response if the row is missing. | `backend/app/routers/overview.py` (`GET /api/overview/summary`), `frontend/src/app/page.tsx`, `frontend/src/components/dashboard/AdoptionOverview/SummaryCards.tsx` (unchanged) |
| FR-OV-02 | Each summary card renders an icon, the metric value in large font, and a descriptive label, using M/K abbreviations where applicable. | Visual and numeric-formatting review confirms consistent abbreviation and layout across cards. | `frontend/.../SummaryCards.tsx` (unchanged) |
| FR-OV-03 | Display a bar chart of org-wide token consumption per month for the last 12 months, zero-padded to 12 entries. | `GET /api/overview/token-series` returns exactly 12 `{month, value}` points sourced from `token_series`. | `backend/app/routers/overview.py` (`GET /api/overview/token-series`), `frontend/.../TokenTrendChartWrapper.tsx` (unchanged) |
| FR-OV-04 | Chart displays the current total and a period-over-period change indicator with direction visually distinguished. | `period_over_period_change` field drives indicator direction. | `backend/app/services/overview.py`, `frontend/.../TokenTrendChart.tsx` (unchanged) |
| FR-OV-05 | The most recent month is visually emphasized relative to prior months. | Visual review confirms emphasis (e.g., color/weight) on the latest bar. | `frontend/.../TokenTrendChartWrapper.tsx` (unchanged) |
| FR-OV-06 | Each bar is labelled with its month. | Month labels render correctly for all 12 bars. | `frontend/.../TokenTrendChartWrapper.tsx` (unchanged) |
| FR-OV-07 | Display a stacked bar chart of MAU by role (Developer, Architect, Product Manager, Engineering Manager) for the last 12 months. | `GET /api/overview/mau-series` returns 12 `{month, developer, architect, product_manager, engineering_manager}` points from `mau_series`. | `backend/app/routers/overview.py` (`GET /api/overview/mau-series`), `frontend/.../MAUStackedBarChart.tsx` (unchanged) |
| FR-OV-08 | Chart displays the current period total and month-over-month change. | Matches backend `period_over_period_change`. | `backend/app/services/overview.py`, `frontend/.../MAUByRoleChart.tsx` (unchanged) |
| FR-OV-09 | Each bar shows the monthly total, is labelled with its month, and a legend identifies each role segment. | Visual review confirms legend and labels present. | `frontend/.../MAUByRoleChart.tsx` (unchanged) |
| FR-OV-10 | Display an adoption-level indicator showing programs using AI SDLC out of total (e.g., "6/9 — 67% of the org"). | `programs_using_ai.count/total/adoption_percent` from `org_summary_rollup`. | `backend/app/routers/overview.py` (`GET /api/overview/summary`), `frontend/.../AdoptionIndicator.tsx` (unchanged) |
| FR-OV-11 | A progress bar visualizes adopted vs. not-yet-adopted programs, with a legend. | Progress bar proportion matches the adoption fraction; legend present. | `frontend/.../AdoptionIndicator.tsx` (unchanged) |
| FR-OV-12 | Display a program board listing every program using Harness, with icon/name, type tag, description, monthly token sparkline with change indicator, totals (tokens, releases, features, active contributors), repos with Harness installed (e.g., "5/6"), and a navigation affordance. | `GET /api/overview/program-board` returns `program_summary` rows ordered by `tokens desc`. | `backend/app/routers/overview.py` (`GET /api/overview/program-board`), `frontend/.../ProgramBoard.tsx`, `ProgramCard.tsx` (unchanged) |
| FR-OV-13 | Selecting a program (card or navigation affordance) navigates to the Program Detail page for that program. | Clicking any program card or its affordance opens the correct Program Detail page. | `frontend/.../ProgramCard.tsx` (unchanged) |
| FR-OV-14 | The program board reflects programs and values sourced dynamically from the backend at runtime (not hardcoded). | No hardcoded/illustrative values appear in a production build; all figures trace to a backend response. | `backend/app/routers/overview.py` |

**CIO / Engineering Manager Program Detail**

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-PD-01 | Display the program icon, name, type tag(s), and description. | Header renders correctly for any selected program. | `frontend/.../ProgramDetailHeader.tsx` (unchanged) |
| FR-PD-02 | Provide a "← Back to program board" control returning to the Adoption Overview. | Control navigates back to the Adoption Overview. | `frontend/.../BackToProgramBoard.tsx` (unchanged) |
| FR-PD-03 | Provide a "Switch program" selector; selecting another program reloads the detail view for that program. | Selecting a different program reloads all Program Detail data for the new selection without a full page navigation to the board. | `frontend/.../ProgramSwitcher.tsx` (unchanged), `backend/app/routers/programs.py` |
| FR-PD-04 | Display program-level summary cards (to date): token consumption, features delivered via Harness, releases done via Harness, repos with Harness installed, commands executed, lines of code generated, user stories delivered. | All seven cards render correct values sourced from the backend program-detail endpoint. | `backend/app/routers/overview.py` (`GET /api/overview/program-detail/{program_id}`), `frontend/.../ProgramSummaryCards.tsx` (unchanged) |
| FR-PD-05 | Display an area/line chart of daily AI token usage for the selected range (default last 30 days). | Chart renders daily data points for the selected range. | `backend/app/services/program_detail.py`, `frontend/.../DailyTokenTrendChart.tsx` (unchanged) |
| FR-PD-06 | Chart displays the period total and average per day. | Total and average match backend-computed values for the selected range. | `backend/app/services/program_detail.py` |
| FR-PD-07 | Chart provides range toggles (7D/30D/90D); changing the range refreshes the chart data. | Selecting a toggle refreshes chart data within the NFR performance target (see §7). | `frontend/.../RangeToggle.tsx` (unchanged), `backend/app/routers/overview.py` |
| FR-PD-08 | Display a paginated releases list for the selected range with total count and 7D/30D/90D toggle. | `GET /api/program-detail/{program_id}/releases?range=&offset=&limit=` (default `offset=0`, `limit=20`, max 50). | `backend/app/routers/program_detail.py` (`GET /api/program-detail/{program_id}/releases`), `frontend/.../ReleasesList.tsx` (unchanged) |
| FR-PD-09 | Each release row shows version, release type (with status indicator), date, number of stories, and PRs merged. | All fields render for each release row. | `frontend/.../ReleasesList.tsx` (unchanged) |
| FR-PD-10 | The release list is scrollable when it exceeds the visible area. | List scrolls without layout breakage when populated beyond the visible area. | `frontend/.../ReleasesList.tsx` (unchanged) |
| FR-PD-11 | Display command activity for the selected range (default 30 days) with total run count and 7D/30D/90D toggles. | Total run count matches the selected range's underlying command data. | `backend/app/services/program_detail.py`, `frontend/.../CommandsActivity.tsx` (unchanged) |
| FR-PD-12 | Each command is listed by name with its run count and a proportional bar. | Proportional bar width is consistent with each command's relative run count. | `frontend/.../CommandsActivity.tsx` (unchanged) |
| FR-PD-13 | Display a project-team table of members and contribution for the selected range (default last 30 days) with 7D/30D/90D toggles. | Table renders and updates correctly per range toggle. | `backend/app/services/program_detail.py`, `frontend/.../TeamTable.tsx` (unchanged) |
| FR-PD-14 | Each member row shows member name, role, sessions, tokens, and avg/session. | All fields render correctly for each member. | `frontend/.../TeamTable.tsx` (unchanged) |
| FR-PD-15 | Display a bar chart of total time in AI coding sessions per day for the selected range (default last 30 days), with 7D/30D/90D toggles. | Reads `session_series` (nullable `member_id` = org/program-wide rollup row). | `backend/app/services/program_detail.py`, `frontend/.../SessionTimeChart.tsx` (unchanged) |
| FR-PD-16 | Chart is filterable by member and shows the period total and average per day. | Selecting a member filters the chart to that member's session time; totals recompute accordingly. | `frontend/.../SessionTimeChart.tsx`, `MemberFilter.tsx` (unchanged) |
| FR-PD-17 | `GET /api/overview/program-detail/{program_id}` returns byte-identical data regardless of whether the caller is the CIO or an Engineering Manager viewing their own program. | No persona-branching logic exists in the endpoint or its service function. | `backend/app/routers/overview.py`, `backend/app/services/program_detail.py` |

**Shared Persona Components** *(used by Architect, Developer, Product Manager, and — where noted — Engineering Manager dashboards)*

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-SH-01 | Each persona dashboard displays the product header (AgentRise Harness / AI SDLC Governance), the signed-in user's name and role, and a persona tag. | Header renders correctly for each of the five personas. | `frontend/.../PersonaHeader.tsx` (unchanged) |
| FR-SH-02 | Each persona dashboard shows the program context in scope: icon, name, type tag, and description. | Program context renders correctly for the program in scope. | `frontend/.../ProgramContext.tsx` (unchanged), `backend/app/routers/programs.py` |
| FR-SH-03 | A subtitle identifies the view (e.g., "Architect overview," "Developer overview," "Product Manager overview," "Engineering manager overview"). | Subtitle matches the signed-in persona. | `frontend/.../PersonaDashboardShell.tsx` (unchanged) |
| FR-SH-04 | For individual-contributor personas (Architect, Developer, Product Manager), display a "Your usage" block scoped to the signed-in user (to date) with cards: sessions, total time, total tokens, avg tokens/session. | All four cards render correct values scoped to the signed-in user. | `backend/app/routers/personal_usage.py` (`GET /api/personal-usage/{user_id}`), `frontend/.../PersonalUsageCards.tsx` (unchanged) |
| FR-SH-05 | Display an area/line chart of the user's daily AI token usage (default last 30 days), with period total, per-day average, and 7D/30D/90D toggles. | Chart and totals scoped correctly to the signed-in user and selected range. | `backend/app/services/personal_usage.py`, `frontend/.../PersonalDailyTokenPanel.tsx` (unchanged) |
| FR-SH-06 | Display a bar chart of the user's total time in AI coding sessions per day (default last 30 days), with period total and 7D/30D/90D toggles. | Chart and total scoped correctly to the signed-in user and selected range. | `backend/app/services/personal_usage.py`, `frontend/.../PersonalSessionTimePanel.tsx` (unchanged) |
| FR-SH-07 | Display the user's command activity (default last 30 days) with total run count and 7D/30D/90D toggles. | Total run count matches the signed-in user's command data for the selected range. | `backend/app/services/personal_usage.py`, `frontend/.../PersonalCommandsPanel.tsx` (unchanged) |
| FR-SH-08 | Each command is listed by name with its run count and a proportional bar. | Proportional bar width consistent with each command's relative run count. | `frontend/.../PersonalCommandsPanel.tsx` (unchanged) |
| FR-SH-09 | Display a session-wise usage table listing the user's individual sessions, each with session name/description, identifier, date, duration, and tokens consumed. | All fields render for each session row. | `backend/app/routers/personal_usage.py`, `frontend/.../PersonalSessionList.tsx` (unchanged) |
| FR-SH-10 | The session table supports pagination when the number of sessions exceeds the visible area. | Pagination controls work correctly across multiple pages. | `backend/app/routers/personal_usage.py` (`page`/`page_size` params, max 100), `frontend/.../PersonalSessionList.tsx` (unchanged) |
| FR-SH-11 | Persona dashboards include a program summary block (to date) equivalent to the CIO Program Detail summary cards. | All seven program-summary metrics render, matching the values shown on the CIO Program Detail page for the same program. | `backend/app/services/program_detail.py`, `frontend/.../ProgramSummaryBlock.tsx` (unchanged) |
| FR-SH-12 | Architect and Product Manager (and, per the reference implementation's 2026-08-07 decision, Developer — see FR-DV-05 below) dashboards display an "Artifacts generated" panel listing program outputs with counts (Product Requirement Docs, User stories, Test cases, Architecture diagrams, API specifications), zero-count types included. | Panel renders all artifact types (including zero-count) with correct counts, backed by `GET /api/artifacts/{program_id}` and `program_artifacts` (unique on `[program_id, type]`). | `backend/app/routers/artifacts.py` (`GET /api/artifacts/{program_id}`), `frontend/.../ArtifactsPanel.tsx` (unchanged) |
| FR-SH-13 | Persona dashboards display the program's releases shipped with Harness (default last 30 days) with total count and 7D/30D/90D toggles; each row shows version, release type, date, stories, and PRs merged. | Release list matches CIO Program Detail data for the same program and range. | `backend/app/services/program_detail.py`, `frontend/.../SharedReleasesList.tsx` (unchanged) |
| FR-SH-14 | Persona dashboards display the project-team contribution table (default last 30 days) with 7D/30D/90D toggles; each row shows member name, role, sessions, tokens, and avg/session. | Table matches CIO Program Detail data for the same program and range. | `backend/app/services/program_detail.py`, `frontend/.../SharedProjectTeamTable.tsx` (unchanged) |
| FR-SH-15 | Persona dashboards display program-level command activity (default last 30 days) with total run count and per-command counts, distinct from the personal "Your commands" component. | Program-level command totals are distinguishable from, and independent of, the signed-in user's personal command totals. | `backend/app/services/program_detail.py` |
| FR-SH-16 | Architect, Product Manager (and Developer, per FR-DV-05) dashboards display a "Compliance & guardrails" panel showing governance status for the program, with an overall status (e.g., "6/7 passing") and, per guardrail, a name and status indicator (Enforced, Warning, or Not Implemented). | `ComplianceGuardrailsPanel.tsx`, backed by `GET /api/guardrails/{program_id}`; pass = `Enforced` or `Warning`. | `backend/app/routers/guardrails.py` (`GET /api/guardrails/{program_id}`), `frontend/.../ComplianceGuardrailsPanel.tsx` (unchanged) |
| FR-SH-17 | Guardrail statuses are color-coded and distinguishable by more than color alone (label/icon). | Accessibility review confirms status is conveyed via label or icon, not color alone. | `frontend/.../ComplianceGuardrailsPanel.tsx` (unchanged) |
| FR-SH-18 | Architect, Product Manager (and Developer) dashboards display an "Organization Constitution" panel summarizing the non-negotiable rules, constraints, best practices, and guiding principles governing AI usage, across four categories (Constraints, Standard, Mandatory, Vision) each with a description and item count. | `OrganizationConstitutionPanel.tsx`, backed by `GET /api/constitution` and `org_constitution` (unique on `[org_id, category]`). | `backend/app/routers/constitution.py` (`GET /api/constitution`), `frontend/.../OrganizationConstitutionPanel.tsx` (unchanged) |
| FR-SH-19 | The Organization Constitution panel provides an "Open full document" control to view the complete constitution. | Control opens/links to the full constitution document. | `frontend/.../OrganizationConstitutionPanel.tsx` (unchanged) |

**Architect Dashboard**

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-AR-01 | Compose the Architect Dashboard from, in order: persona header/context, "Your usage" cards, daily token chart, daily session-time chart, your commands, session-wise usage (paginated), program summary, artifacts generated, releases, project team, program-level commands, compliance & guardrails, Organization Constitution. | Dashboard renders all listed components in the specified order for the signed-in architect. | `frontend/.../ArchitectDashboard.tsx` (unchanged) |
| FR-AR-02 | All time-series and list components provide 7D/30D/90D toggles defaulting to 30 days. | Every applicable component exposes and defaults correctly to the range toggle. | `frontend/.../ArchitectDashboard.tsx` (unchanged) |
| FR-AR-03 | The dashboard is scoped to the signed-in architect for personal components and to the program in context for program-level components. | Personal data never includes another user's data; program data reflects only the program in context. | `backend/app/core/rbac.py` |

**Developer Dashboard**

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-DV-01 | Compose the Developer Dashboard from, in order: persona header/context (Developer tag, "Developer overview" subtitle), "Your usage" cards, daily token chart, daily session-time chart, your commands, session-wise usage (paginated), program summary, artifacts generated, releases, project team, program-level commands, compliance & guardrails, Organization Constitution — full-fidelity, per FR-DV-05. | Dashboard renders all listed components in the specified order for the signed-in developer. | `frontend/.../DeveloperDashboard.tsx` (unchanged) |
| FR-DV-02 | All time-series and list components provide 7D/30D/90D toggles defaulting to 30 days. | Every applicable component exposes and defaults correctly to the range toggle. | `frontend/.../DeveloperDashboard.tsx` (unchanged) |
| FR-DV-03 | Personal components are scoped to the signed-in developer; program-level components to the program in context. | Personal data never includes another user's data; program data reflects only the program in context. | `backend/app/core/rbac.py` |
| FR-DV-05 | The Developer Dashboard includes Compliance & Guardrails, Organization Constitution, and Artifacts panels at full fidelity — no lightweight variant, reproducing the reference implementation's 2026-08-07 scope reversal (DEV-02). | The governance-visibility check's allowed-persona set includes `"developer"`; `DeveloperDashboard.tsx` renders all 3 governance panels. | `backend/app/core/rbac.py` (governance check) |

**Product Manager Dashboard**

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-PM-01 | Compose the Product Manager Dashboard from, in order: persona header/context (Product Manager tag, "Product Manager overview" subtitle), "Your usage" cards, daily token chart, daily session-time chart, your commands, session-wise usage (paginated), program summary, artifacts generated, releases, project team, program-level commands, compliance & guardrails, Organization Constitution. | Dashboard renders all listed components in the specified order for the signed-in product manager. | `frontend/.../ProductManagerDashboard.tsx` (unchanged) |
| FR-PM-02 | All time-series and list components provide 7D/30D/90D toggles defaulting to 30 days. | Every applicable component exposes and defaults correctly to the range toggle. | `frontend/.../ProductManagerDashboard.tsx` (unchanged) |
| FR-PM-03 | Personal components are scoped to the signed-in product manager; program-level components to the program in context. | Personal data never includes another user's data; program data reflects only the program in context. | `backend/app/core/rbac.py` |

**Engineering Manager Dashboard**

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-EM-01 | Display the persona header with the Eng Manager tag and "Engineering manager overview" subtitle, plus program context (icon, name, type, description). | Header and program context render correctly. | `frontend/.../EngineeringManagerDashboard.tsx` (unchanged) |
| FR-EM-02 | Provide a "Switch program" selector limited to programs the manager belongs to; selecting another program reloads the view for that program. | Selector lists only the manager's own programs; selecting one reloads all program-detail data. | `backend/app/routers/programs.py` |
| FR-EM-03 | Display program summary cards per FR-PD-04. | Cards match the equivalent CIO Program Detail data for the same program. | `backend/app/services/program_detail.py` |
| FR-EM-04 | Display daily token consumption per FR-PD-05 to FR-PD-07. | Chart and range toggles behave identically to CIO Program Detail for the same program. | `backend/app/services/program_detail.py` |
| FR-EM-05 | Display releases via Harness per FR-PD-08 to FR-PD-10. | Release list behaves identically to CIO Program Detail for the same program. | `backend/app/routers/program_detail.py` |
| FR-EM-06 | Display commands executed — program — per FR-PD-11 to FR-PD-12. | Command activity behaves identically to CIO Program Detail for the same program. | `backend/app/services/program_detail.py` |
| FR-EM-07 | Display the project-team table per FR-PD-13 to FR-PD-14. | Team table behaves identically to CIO Program Detail for the same program. | `backend/app/services/program_detail.py` |
| FR-EM-08 | Display daily session time by member with a member selector, per FR-PD-15 to FR-PD-16. | Chart and member filter behave identically to CIO Program Detail for the same program. | `backend/app/services/program_detail.py` |

**Activity & Artifact Ingestion (MCP + Batch)**

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-ING-01 | Expose an MCP server (`services/mcp-server`, package `agentrise_mcp`, FastMCP, streamable HTTP transport, default `0.0.0.0:3010`, unchanged from the reference implementation) with two tools: `push_activity(program_id?, workspace_root?)` and `push_artifacts(program_id?, workspace_root?)`. | `python -m agentrise_mcp.server` (or the `agentrise-mcp` console script) starts a server exposing exactly these 2 tools at `/mcp` — same startup contract as the reference implementation. | `services/mcp-server/` (carried over unchanged) |
| FR-ING-02 | `push_activity` reads `.harness/profile.yaml`'s `files:` entries (kind=`activity`), parses each as NDJSON (skipping blank/malformed lines), batches rows 500/request, and POSTs each batch to the ingest endpoint as `{program_id, kind:"activity", rows}`. | Returns a push result with `files_read`, `rows_read`, `batches`, `inserted`, `skipped_duplicate`, `rejected`, `rollups` — same response shape as the reference implementation's `PushResult`. | `services/mcp-server/src/agentrise_mcp/tools/push_activity.py` (unchanged) |
| FR-ING-03 | `push_artifacts` reads the `artifacts:` block of `.harness/profile.yaml` (source kinds `glob-count`, `json-key-count`, `json-field-sum`, `constant`), resolves each to an integer count against the local filesystem, and POSTs `{program_id, kind:"artifacts", counts, as_of}` to the artifacts ingest endpoint. | Returns a push-artifacts result — same response shape as the reference implementation's `PushArtifactsResult`. | `services/mcp-server/src/agentrise_mcp/tools/push_artifacts.py` (unchanged) |
| FR-ING-04 | `POST /api/ingest/files` authenticates via bearer-token hash lookup, authorizes via program-scope check, caps at 5000 rows/request (413 over), validates every row (Pydantic schema), upserts `usage_events` (idempotent on `[program_id, session_id, cmd_ts]`), then synchronously rebuilds program and org rollups. | Response includes received/valid/inserted/updated/rejected counts + reasons + rollup summaries — same contract shape as the reference implementation. | `backend/app/routers/ingest.py`, `backend/app/services/ingest.py` |
| FR-ING-05 | `POST /api/ingest/artifacts` uses the same auth/authz, validates counts against the 5 canonical artifact types, upserts artifact rows in one transaction (idempotent). | Re-sending the same payload produces the same end state. | `backend/app/routers/ingest.py` |
| FR-ING-06 | A CLI command mints a raw bearer token (`"hrn_pat_" + 24 random bytes hex`), prints it once, and persists only its SHA-256 hash plus label/email/allowed-program-ids. The raw value is never stored server-side. | Token database row never contains the raw secret. | `backend/app/cli/mint_ingest_token.py` (Typer CLI, replacing `scripts/mint-ingest-token.ts`) |
| FR-ING-07 | A Node hook pair bridges VS Code Copilot Chat sessions into the same pipeline without an MCP client in the loop, carried over unchanged from the reference implementation: `copilot-activity.mjs` (triggered on Copilot Chat `sessionEnd`/`Stop`) parses the local chat-session + transcript journals, computes per-command duration, intervention count, files created/modified, lines added, tool rejections, outcome, and per-model token aggregates, and appends/upserts one JSON record per line (keyed by `session_id`+`cmd_ts`) into `docs/activity/activity.jsonl`; it then spawns `harness-mcp-push.mjs` detached, which manually speaks the MCP streamable-HTTP JSON-RPC protocol (`initialize` → `notifications/initialized` → `tools/call push_activity` → `DELETE`) against `HARNESS_MCP_URL` (default `http://127.0.0.1:3010/mcp`, IPv4 loopback deliberately to avoid Windows IPv6 resolution issues) to push the freshly written activity. Because this bridge targets the MCP server's HTTP endpoint directly, it is entirely backend-agnostic and requires no change for this edition. | A completed Copilot Chat slash-command session results in a new/updated `docs/activity/activity.jsonl` line and a best-effort MCP push, logged to `docs/activity/.mcp-push.log`, without blocking the calling hook on failure — same contract as the reference implementation. | `.github/hooks/copilot-activity.mjs`, `.github/hooks/harness-mcp-push.mjs` (carried over unchanged — these never talk to the Next.js/FastAPI backend directly, only to the MCP server) |
| FR-ING-08 | A manual CLI ingester reads every activity JSONL file under the activity log directory and runs the identical validate → upsert → rebuild-rollups pipeline as the HTTP route, ingesting into a fixed self-referential program id, for dogfooding this project's own build activity. | CLI and MCP-push paths produce identical DB state for the same input rows (shared service functions). | `backend/app/cli/ingest.py` (replacing `scripts/ingest.ts`) |
| FR-ING-09 | An admin repo-scan endpoint authenticates via bearer token, scans a configured GitHub org for Harness installation, and updates the org rollup's repo counts. | Requires GitHub org + token settings. | `backend/app/routers/admin.py` (`POST /api/admin/scan-repos`) |

**Backend / Data**

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-BE-01 | `GET /api/overview/summary`, `/token-series`, `/mau-series`, `/program-board` — all CIO-only, no params (except program-board's implicit sort). | Endpoints return the fields required by FR-OV-01..14. | `backend/app/routers/overview.py` |
| FR-BE-02 | Every time-series/list endpoint supports `range=7d\|30d\|90d`; **400** on invalid value, matching the reference implementation's contract exactly. | Verified on program-detail, releases, personal-usage routes. Must return 400, not FastAPI's framework-default 422 — implement via an explicit check (custom exception handler or manual validation), not a raw Pydantic/Enum type-coercion error, so any existing API consumer built against the reference contract keeps working unchanged. | Multiple routers |
| FR-BE-03 | Support `member_id` on the daily session-time series, and `page`/`page_size` (max 100) plus `offset`/`limit` (max 50, per-endpoint) pagination where applicable. | `SessionTimeChart`/`MemberFilter` (frontend, unchanged); `PersonalSessionList` (frontend, unchanged); `ReleasesList` (frontend, unchanged), backed by the FastAPI equivalents of these routes. | Multiple routers |
| FR-BE-04 | All derived values (adoption %, deltas, averages, "X/Y passing") computed server-side, never client-side. | No derived value computed only in a frontend component. | `backend/app/services/*.py` |
| FR-BE-05 | Ingest freshness tracked via a system-metadata singleton row, read through a cached accessor; raises if the row is absent. | Frontend renders the freshness timestamp on every dashboard view. | `backend/app/services/freshness.py` |
| FR-BE-06 | Every ingest write is idempotent: re-sending the same payload creates no duplicates and no double-counted rollups. | Enforced via DB-level unique constraints plus upsert semantics — same constraint shape as the reference schema. | `backend/app/models/*.py` (SQLAlchemy) |
| FR-BE-07 | Rollups are always **fully rebuilt** from `usage_events`, never incrementally patched, on every successful ingest write. | `rebuild_program_rollups`/`rebuild_org_rollups` re-derive every affected rollup table from the raw event table — same invariant as reference PRD FR-BE-07 (A-002). | `backend/app/services/ingest.py` |
| FR-BE-08 | Consistent numeric (M/K) and time (h/m) formatting across all views. | Formatting can live frontend-side (display-only) or backend-side (pre-formatted strings) — pick one and apply consistently; do not mix. | Frontend formatting utils (unchanged) or `backend/app/utils/format.py` |

### 6.2 Should Have — Important, Not Launch Blockers

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-SH-20 | Support additional executive/leadership viewers beyond the original CIO with the same read-only, all-programs access, granted purely via config (no code change/deploy). | A second executive role slug (e.g. `cxo`, `board_member`) added to any of the 3 persona-resolver sources resolves to `cio` within 5 minutes. | `backend/app/core/persona_resolver.py` |
| FR-SH-21 | Clicking a guardrail or Organization Constitution reference opens the relevant external `document_ref` document. | Selecting the item navigates to the correct external URL. | Frontend components (unchanged) |
| FR-ING-10 | A role-sync CLI mirrors Keycloak role assignments into a reference/audit table (`email` PK, `role`, `source`, `synced_at`), using a Keycloak service-account client (admin client id/secret with `view-users` + `query-groups` on `realm-management`). | Running the CLI populates/updates the reference table without altering live session behavior (session role still comes from the token claims at sign-in time). | `backend/app/cli/sync_user_roles.py` (replacing `scripts/sync-user-roles.ts`) |

### 6.3 Could Have — Nice to Have

| ID | Requirement | Acceptance Criteria | Source (this edition) |
|----|-------------|--------------------|----|
| FR-SH-22 | Extend role segmentation for MAU-by-role and team-role reporting beyond the current 4 roles (Developer/Architect/Product Manager/Engineering Manager) if a finer role taxonomy (e.g. QA) is ever required. | Additional role segments appear in MAU/team tables via an explicit Alembic migration (fields would need to be added to `mau_series`). | `backend/alembic/versions/` |
| FR-ING-11 | Add a scheduler (cron) to run the CLI ingester or an equivalent batch job automatically, replacing today's fully manual trigger. | A scheduled job runs on a defined cadence and updates `system_metadata.last_successful_run_at` without manual intervention. | Candidate: APScheduler in-process, or an external cron calling the CLI ingester / MCP push |

### 6.4 Won't Have — This Version (Parking Lot)

| ID | Requirement | Reason Deferred | Revisit Version |
|----|-------------|----------------|----------------|
| FR-P01 | Any browser-reachable creation/editing UI for program, constitution, guardrail, or artifact data. | Read-only reporting layer by design; the only write surface is the bearer-token ingest API, intentionally unreachable from the UI. | {TBD} |
| FR-P02 | User administration and provisioning inside the dashboard. | Handled by Keycloak / the org's IAM processes; the role-sync CLI only mirrors, never creates. | {TBD} |
| FR-P03 | Configuration or enforcement of the underlying AI tooling/guardrails from within the dashboard. | Dashboard reports guardrail status; it does not run the checks. | {TBD} |
| FR-P05 | PDF/CSV export of any dashboard view. | Not implemented; no export route/component planned for this version. | {TBD} |
| FR-P06 | Automated/scheduled ingestion (cron). | The CLI ingester and MCP `push_*` tools are manually triggered for this version; see FR-ING-11 (Could Have) for the deferred version. | {TBD} |

---

## 7. Non-Functional Requirements

*(Targets identical to the reference PRD §7 — measurement methods updated where the tool changes.)*

| ID | Category | Requirement | Target | Measurement Method | Notes |
|----|----------|-------------|--------|--------------------|-------|
| NFR-001 | Performance | Dashboard render time | ≤ 3s under normal load | Synthetic monitoring | Same target as reference implementation. |
| NFR-002 | Performance | Range/filter change refresh time | ≤ 2s | Synthetic monitoring | Now measures a cross-origin-feeling (same-proxy) fetch from Next.js to FastAPI — worth confirming the proxy hop doesn't add material latency. |
| NFR-003 | Availability | Uptime during business hours | 99.5% | Uptime monitoring | Applies to both services (frontend and backend) plus the reverse proxy. |
| NFR-004 | Scalability | Program and contributor/repo growth | Support all 9 programs and continued growth without redesign | Load testing | Rollup-rebuild-on-every-write is O(events for the affected program) per write, same as reference implementation — same scaling caveat applies. |
| NFR-005 | Security | Authentication | Keycloak OIDC via FastAPI/Authlib; server-side RBAC (never UI-only hiding) | Security review | See §9.1. |
| NFR-006 | Security | Ingest write authorization | Bearer-token auth, scoped by allowed-program-ids, never session-cookie auth | Security review | Same model as reference implementation. |
| NFR-007 | Privacy | Individual-usage data handling | Visible only to self, CIO, and per-member-popup exception within a shared program | Privacy review | Same model as reference implementation. |
| NFR-008 | Accessibility | WCAG level | AA, where feasible | Automated + manual audit | Frontend unchanged, so existing accessibility work carries over. |
| NFR-009 | Compatibility | Browser / device | Standard desktop browser resolutions only; no mobile target for v1 | Cross-browser testing | Unchanged. |
| NFR-010 | Data Freshness | Freshness signal | System-metadata singleton, no automatic staleness computation | Ingestion job monitoring | Same gap as reference implementation (§2.3, FR-ING-11) — carried over, not fixed by the language change. |
| NFR-011 | Auditability & Logging | Structured access logging | Python `structlog`/`logging` JSON output for RBAC checks and telemetry events | Log review | Replaces Pino; same event set (`rbac_check_org_access`, `individual_view_denied`, `member_view_denied`, `dashboard_login`, `program_drilldown`, `program_switch`, `persona_mapping_loaded`). |
| NFR-012 | Idempotency | Every ingest write path is safely retryable | Re-POSTing an identical batch produces no duplicate rows and no double-counted rollups | Automated test (pytest) against the ingest endpoints | Backed by DB-level unique constraints (FR-BE-06). |
| NFR-013 | Localization | Languages | {TBD} | | Not addressed in the reference implementation either. |
| NFR-014 | Data Retention | Retention period for `usage_events`/session rows | {TBD} | | Same open gap as reference implementation — recommend defining before this build's launch, not carrying the gap forward silently. |

---

## 8. Technical Constraints & Dependencies

### 8.1 Platform & Framework Constraints

- **Two-service architecture**: FastAPI backend (`backend/`, Python 3.12, Poetry or `uv` for dependency management) + Next.js/TypeScript frontend (`frontend/`, unchanged component/chart library, pnpm). A reverse proxy (or Next.js `rewrites()` for local dev) routes `/api/*` to FastAPI and everything else to Next.js, presenting one logical origin to the browser.
- PostgreSQL as the sole system of record, accessed via SQLAlchemy 2.0 (async) with Alembic migrations, replacing Prisma. Same 17-table shape as the reference schema (§8.4).
- The MCP server (`services/mcp-server`) is carried over unchanged — already Python/FastMCP — and now naturally shares its language and toolchain with the main backend. Sharing Pydantic schemas between the two is a reasonable follow-on optimization, not a requirement for this version.
- Charting stays `recharts` v2.x on the unchanged frontend; no charting-library decision to make in this edition.
- **Auth**: FastAPI owns the entire Keycloak OIDC session lifecycle via Authlib, setting a session cookie the frontend relies on. RBAC is enforced server-side in FastAPI dependencies, never merely hidden in the frontend.
- Data is populated by push-based ingestion (MCP tools, hooks, manual CLI), never polled by the backend from any upstream system on each request; rollups are precomputed at write time, read synchronously at request time — same model as the reference implementation.
- Every time-series/list API endpoint supports a `range` parameter, plus member/pagination parameters where applicable.
- Derived values are computed server-side (Python), never in the frontend.
- The application is read-only from the browser end-to-end; the only write paths are the bearer-token-authenticated ingest/admin endpoints, which never accept a session cookie as authorization.
- Internal desktop browsers only — no mobile target for v1.

### 8.2 Integration Dependencies

| System / API | Integration Type | Required For | Owner | Status |
|-------------|-----------------|--------------|-------|--------|
| Keycloak (self-hosted OIDC IdP) | OIDC via Authlib (FastAPI) | Authentication for all five personas; drives server-side RBAC via `role`/`groups` claims | {TBD} | Same IdP as the reference implementation; new client registration needed for this edition's callback URL. |
| Program-membership source of truth | IdP group claims, configurable prefix (default `"program-"`) | Scoping `/api/programs`; "Switch program" selector limits | Product / Platform | Same source as reference implementation. |
| MCP server (`services/mcp-server`) | Local HTTP (streamable MCP protocol) | `push_activity`/`push_artifacts` tools, feeding all usage-event-derived views | Platform/DevEx | Carried over unchanged; now talks to the FastAPI backend's ingest endpoints instead of Next.js Route Handlers — endpoint paths stay the same. |
| Ingest API (`/api/ingest/files`, `/api/ingest/artifacts`) | Internal REST, bearer-token auth | Receives all MCP/hook/CLI pushes | Platform/DevEx | Re-implemented in FastAPI; same request/response contract as the reference implementation. |
| GitHub API | REST, PAT auth | Admin repo-scan → repo-installed counts | {TBD} | Same integration as reference implementation, re-implemented with an async Python HTTP client. |
| Organization's PostgreSQL database | SQLAlchemy 2.0 (async) + Alembic | Storage/aggregation of all 17 core data models (§8.4) | {TBD} | Same physical schema shape as the reference implementation, defined via SQLAlchemy models instead of a Prisma schema file. |
| Keycloak admin service account (optional) | Keycloak Admin REST API | Role-sync CLI mirrors role assignments into a reference table | {TBD} | Same integration as reference implementation. |

### 8.3 Third-Party Services

*(Unchanged from the reference PRD §8.3.)*

| Service | Purpose | License / Cost | Risk if Unavailable |
|---------|---------|----------------|---------------------|
| Keycloak | OIDC identity provider | Self-hosted | Auth blocked in production; dev-bypass remains available in non-production only |
| GitHub API | Repo-scan for Harness-installed count | Standard GitHub org access via PAT | Repo-scan endpoint fails; repo counts go stale until manually corrected or retried |

No product-analytics SaaS or BI tool is used.

### 8.4 Data Model (High Level)

Same 17-model shape as the reference implementation's Prisma schema (`docs/prd/agentrise-harness-adoption-platform.md` §8.4), re-expressed as SQLAlchemy 2.0 declarative models + Alembic migrations. Table names (snake_case), unique constraints, and field semantics should be reproduced 1:1 so the frontend's data expectations (component props, chart series shapes) don't need to change. Type mapping: Prisma `BigInt` → SQLAlchemy `BigInteger`; `Json` → `JSON`/`JSONB`; `String[]` → `postgresql.ARRAY(String)`; discriminator fields stay plain `String` (no Postgres enums, matching the reference implementation's own choice not to use them).

**Org/program rollups (read path, rebuilt on every ingest write):**
- `org_summary_rollup` — singleton per org (`org_id` unique, default `"org-1"`): `programs_using_ai_count Integer`, `programs_total Integer`, `total_token_consumption BigInteger`, `lines_of_code_generated BigInteger`, `releases_using_harness Integer`, `repos_with_harness_installed Integer`, `repos_total Integer`, `as_of_timestamp DateTime(timezone=True)`, `created_at`, `updated_at`.
- `token_series` — unique `(org_id, month)`: `month String (YYYY-MM)`, `value BigInteger`, `as_of_timestamp`.
- `mau_series` — unique `(org_id, month)`: `developer Integer`, `architect Integer`, `product_manager Integer`, `engineering_manager Integer`.
- `program_summary` — `program_id String unique`: `name, icon, type, description`, `monthly_token_sparkline JSON`, `tokens BigInteger`, `releases Integer`, `features Integer`, `active_contributors Integer`, `repos_with_harness_installed Integer`, `repos_total Integer`, plus `commands_executed Integer`, `lines_of_code_generated BigInteger`, `user_stories_delivered Integer`, plus `intervention_count Integer`, `tool_rejections Integer` (nullable, carried over from the reference schema's activity-hook-v2 extensions).
- `program_releases` — `program_id, version, type ("major"|"minor"|"patch"), date, story_count, pr_count, as_of_timestamp`.
- `program_commands` — `program_id, name, run_count, period_start, period_end, as_of_timestamp`.
- `program_members` — `program_id, user_id, name, role, sessions, tokens BigInteger, last_active_date, as_of_timestamp`.
- `session_series` — unique `(org_id, program_id, member_id, date)`: `member_id String nullable` (nullable = org/program-wide rollup row), `date, session_time_seconds Integer, as_of_timestamp`.
- `program_token_series` — unique `(program_id, date)`: `tokens BigInteger`, plus `input_tokens/output_tokens/cache_read_tokens/cache_write_tokens Integer default 0` (per-model token breakdown, carried over from the reference schema), `as_of_timestamp`.
- `user_sessions` — unique `session_identifier`: `user_id, program_id, session_identifier, name, started_at DateTime, duration_seconds Integer, tokens BigInteger`. Individual session rows backing the personal session-wise usage table.

**Governance / static reference data:**
- `program_artifacts` — unique `(program_id, type)`: `type ("prd"|"user_story"|"test_case"|"arch_diagram"|"api_spec")`, `count Integer`, `as_of_timestamp`.
- `program_guardrails` — unique `(program_id, name)`: `status ("Enforced"|"Warning"|"NotImplemented")`, `document_ref String nullable`, `display_order Integer`.
- `org_constitution` — unique `(org_id, category)`: `category ("Constraints"|"Standard"|"Mandatory"|"Vision")`, `description`, `item_count Integer`, `document_ref String`, `display_order Integer`.

**Ingestion / auth / system:**
- `usage_events` — unique `(program_id, session_id, cmd_ts)`: `ts, cmd_ts, user, session_id, kind String nullable, command, feature String nullable, duration_seconds, outcome, intervention_count Integer nullable, files_created Integer nullable, files_modified Integer nullable, lines_added Integer nullable, tool_rejections Integer nullable, input_token/output_token/cache_read/cache_write Integer nullable, total BigInteger, models JSON nullable`. Indexed on `(program_id, ts)`, `(program_id, user)`, `(program_id, command)`, `(program_id, session_id)`. **Source of truth from which every rollup above is rebuilt.**
- `ingest_tokens` — `token_hash String unique` (SHA-256 hex, raw token never stored): `label, user_email, allowed_program_ids postgresql.ARRAY(String)` (or the literal wildcard `"*"`), `expires_at nullable, revoked_at nullable, last_used_at nullable`. Indexed on `user_email`.
- `system_metadata` — `key String primary key` (e.g. `"ingestion"`): `last_successful_run_at DateTime(timezone=True)`. Drives the freshness timestamp.
- `persona_config` — `role String primary key`: `persona String`. Config-driven RBAC (lowest-precedence tier of the 3-tier resolver, FR-AUTH-03).
- `user_roles` — `email String primary key`: `role String`, `source String default "keycloak"`, `synced_at DateTime`. Populated by the role-sync CLI (FR-ING-10); reference/audit only, not read at session time.

**Rebuild invariant** (carried over unchanged, A-002): `usage_events` is append/upsert-only; a program-rollup-rebuild and an org-rollup-rebuild function fully re-derive every rollup table above from that raw table on every successful ingest write — never incremental patches. This is what makes ingestion idempotent and safe to retry (FR-BE-06/07, NFR-012).

### 8.5 Compliance & Regulatory Requirements

*(Unchanged from the reference PRD §8.5 — a language/framework choice has no bearing on regulatory scope.)* No external regulatory framework is named. "Compliance" refers to the governance/guardrail feature the dashboard reports on, not an external regulation the platform itself must satisfy.

---

## 9. Security & Privacy

> This section documents the target design for this edition. Validate with the Security team before development begins, especially §9.1's auth-bridging design (A-006).

### 9.1 Authentication & Authorization

Two entirely separate trust domains, same as the reference implementation:

- **Human/browser sessions** — FastAPI owns the full Keycloak OIDC flow via Authlib: redirect to Keycloak, handle the callback, resolve the persona and program memberships from the token claims, and set a session cookie (httpOnly, `SameSite=Lax`, scoped to the shared origin established by the reverse proxy). The Next.js frontend never talks to Keycloak directly and never handles tokens — it just forwards the cookie on every API call. RBAC is enforced server-side in FastAPI dependencies on every route:
  - **CIO** — org-wide access; sees all programs, org aggregates, any Program Detail; only persona allowed to view another user's individual usage or another member's popup.
  - **Architect, Developer, Product Manager** — governance-eligible; personal-usage data scoped to self; program aggregate data is **not** membership-scoped for viewing (open-aggregate model, FR-AUTH-06, reproduced from the reference implementation per A-004) but the program *list*/switcher **is** scoped to membership (FR-AUTH-10).
  - **Engineering Manager** — program-level team view for their own programs; explicitly **excluded** from governance data.
  - Dev-bypass skips auth/RBAC entirely when active and is unreachable in production.
- **Machine/CI ingestion clients** — authenticate via bearer ingest-token credentials only, scoped per-token to allowed program ids. Never accept a session cookie; never reach any page route.

**Design note (A-006):** this cookie-based bridging assumes the frontend and backend are deployed behind a shared reverse proxy or the same effective origin. If a future deploy topology puts them on genuinely separate origins with no shared proxy, this section needs to move to a token-based bridging pattern (e.g., the backend issues a short-lived JWT the frontend stores and attaches as an `Authorization` header) instead of a cookie. Flag this explicitly during infrastructure planning, not after the auth module is built.

### 9.2 Data Classification

*(Identical to the reference PRD §9.2 — data sensitivity doesn't change with the implementation language.)*

| Data Type | Classification | Storage | Encryption at Rest | Encryption in Transit |
|-----------|---------------|---------|-------------------|----------------------|
| Raw usage events (`usage_events`) — command, duration, tokens, files touched, tied to a named user/session | Confidential (individual activity detail) | Postgres | Expected — standard org practice | Expected — standard org practice |
| Individual session rows (`user_sessions`) and per-member rollups (`program_members`, `session_series`) | Confidential | Postgres | Expected | Expected |
| Program-level aggregate metrics (`program_summary`, `program_releases`, `program_commands`, `program_token_series`) | Internal | Postgres | Expected | Expected |
| Organization-wide aggregate metrics (`org_summary_rollup`, `token_series`, `mau_series`) | Internal | Postgres | Expected | Expected |
| Guardrail status, Organization Constitution content | Internal | Postgres + linked external governance documents (`document_ref`) | Expected | Expected |
| Ingest token hashes (`ingest_tokens.token_hash`) | Confidential (credential material, hashed) | Postgres | Expected | Expected — bearer token sent only over the ingest API's HTTPS/TLS transport in production |
| Local MCP env file (raw ingest token, Keycloak client secret) | Confidential (live credential) | Developer's local filesystem only, gitignored | N/A — local file, not stored server-side raw | N/A |

### 9.3 Threat Model (Summary)

*(Same threats as the reference implementation, since RBAC design and data model are reproduced 1:1; one new row for the auth-bridging design.)*

| Threat | Likelihood | Impact | Mitigation |
|--------|------------|--------|------------|
| Cross-program aggregate data over-exposure (open-aggregate model, by design) | High (default behavior) | Medium | Accepted risk, reproduced intentionally from the reference implementation (A-004); the program-visibility check is the single choke point to tighten if needed. |
| Exposure of individual-level performance data to unauthorized personas | Medium | High | Self-or-CIO gating, denials logged. |
| Leaked or overly broad ingest token (`"*"` scope) | Medium | High | Hashed at rest; revocation/expiry supported; no rotation automation. |
| Compromised Keycloak credentials | Low | High | Relies on the IdP's own controls. |
| Malformed/adversarial ingest payload | Medium | Low | Row cap, per-row validation, program-scope enforcement before any write. |
| Data exfiltration via bulk scraping of aggregate endpoints | Low | Medium | Pagination present on list endpoints (releases, personal sessions); no explicit rate limiting planned for this build — worth adding before treating as fully mitigated. |
| Session-cookie bridging misconfigured across origins (new to this edition — see A-006) | Medium (until infra topology is confirmed) | Medium | Confirm reverse-proxy/shared-origin deploy topology during infrastructure planning, before building the auth module; document the fallback token-based design if that assumption fails. |

### 9.4 Privacy by Design Principles Applied

*(Unchanged from the reference PRD §9.4.)*

- Data minimization / purpose limitation — governance panels absent entirely from the API response for non-eligible personas.
- Scoped visibility for individual data — self and CIO only, with the audited per-member-popup exception.
- No new PII collection.
- Read-only browser surface — every write path requires a machine bearer token.
- Idempotent, replayable ingestion.

---

## 10. Analytics & Instrumentation

### 10.1 Measurement Approach

Adoption %/token trends computed directly from Postgres rollups by the FastAPI backend. Dashboard-of-the-dashboard usage captured via structured Python logging (`structlog` or the standard library `logging` with a JSON formatter), replacing Pino but emitting the same event set.

### 10.2 Key Events to Track

*(Identical event set to the reference PRD §10.2.)*

| Event Name | Trigger | Properties | Used By |
|------------|---------|------------|---------|
| `dashboard_login` | User authenticates and lands on their persona dashboard | user id, persona, timestamp | Usage/adoption tracking |
| `program_drilldown` | User opens Program Detail | user id, persona, program id, timestamp | Program-review analysis |
| `program_switch` | User selects a different program | user id, persona, from/to program id, timestamp | EM/CIO usage patterns |
| `rbac_check_org_access` | Every org-access check evaluation | user id, persona, authorized (bool), timestamp | Security audit |
| `persona_mapping_loaded` | Every persona resolution | role, resolved persona, source tier, timestamp | Auditing mapping source |
| `individual_view_denied` | Individual-usage check denies | requesting/target user, timestamp | Monitoring inappropriate access attempts |
| `member_view_denied` | Member-in-program check denies | requesting/target user, program id, timestamp | Monitoring inappropriate popup access |

---

## 11. Success Metrics & KPIs

*(Identical targets to the reference PRD §11 — reproduce the same seed-fixture baseline in this build's own seed script for a fair comparison.)*

### 11.1 North Star Metric

> Program adoption %: share of programs (target 9/9) using AI SDLC tooling, measured by ≥1 repository per program having Harness installed.

### 11.2 Primary KPIs

| KPI | Baseline (target for this build's seed fixture) | Target | Measurement Window | Owner |
|-----|----------|--------|-------------------|-------|
| Program adoption % | 67% (6/9) — reproduce the reference implementation's seed shape | 100% (9/9) | {TBD} | {TBD} |
| Organization-wide token consumption trend | ~328.8M tokens to date — reproduce the reference implementation's seed shape | Directional trend visibility | Monthly | {TBD} |
| Ingest pipeline health | N/A (manual trigger) | 0 failed manual/MCP-push runs per week once a scheduler exists | Weekly | Platform/DevEx |

### 11.3 Counter Metrics (Guard Rails)

*(Identical to the reference PRD §11.3.)*

| Counter Metric | Alert Threshold | Action if Breached |
|---------------|----------------|-------------------|
| Count of `NotImplemented` guardrails | Any increase month-over-month | Escalate to the program's Architect/PM/EM. |
| Dashboard render/refresh time | Exceeds NFR-001/002 targets | Investigate rollup-rebuild cost and the frontend↔backend proxy hop. |
| `rejected` row count per ingest batch | Any sustained non-zero | Investigate source hook/journal format drift. |
| Unauthorized-access denials | Any sustained non-zero rate | Security review of the affected persona/program path. |

---

## 12. Risks & Mitigations

| ID | Risk | Category | Probability | Impact | Mitigation | Owner | Status |
|----|------|----------|-------------|--------|------------|-------|--------|
| R-001 | `usage_events` has no retention/archival policy; unbounded growth degrades rollup-rebuild performance over time (rebuild is O(events) per write, per NFR-004) — same risk as the reference implementation, not introduced by this rewrite. | Technical | Medium | Medium | Define a retention window with Data Engineering/Legal (NFR-014); consider incremental rollup maintenance if full-rebuild cost becomes prohibitive. | {TBD} | Open |
| R-002 | No scheduler exists for the CLI ingester/MCP pushes; data freshness depends entirely on developers/CI manually triggering ingestion — same gap as the reference implementation. | Organizational | Medium | Medium | Track as FR-ING-11 (Could Have); until then, `system_metadata.last_successful_run_at` staleness is the forcing function that should surface the gap on every dashboard view. | {TBD} | Open |
| R-003 | The open-aggregate RBAC model (FR-AUTH-06) means any authenticated user can view any program's aggregate data; if organizational policy actually requires membership-scoped aggregate access, this is a live gap, not a hypothetical one — reproduced intentionally from the reference implementation (A-004), but worth re-confirming for this build specifically before it reaches real users. | Security | Medium | High | Re-confirm the intended RBAC model with Product/Security; the program-visibility check in `backend/app/core/rbac.py` is the single choke point to tighten if the model needs to change. | {TBD} | Open |
| R-004 | Ingest tokens minted with `"*"` scope have unbounded write scope across all current and future programs, with no automated rotation or expiry enforcement beyond the optional `expires_at` field. | Security | Medium | High | Prefer scoped (non-`"*"`) tokens per developer/program where feasible; document a rotation cadence; consider alerting on tokens with no `expires_at` set. | {TBD} | Open |
| R-005 | Role taxonomy for MAU segmentation and team roles is fixed to 4 roles in the schema (`mau_series` has exactly `developer`/`architect`/`product_manager`/`engineering_manager` columns); adding a 5th role (e.g. QA) requires an Alembic migration, not just config. | Product | Low | Medium | If role taxonomy needs to expand, plan the `mau_series` schema change explicitly rather than assuming it's config-driven like persona mapping. | {TBD} | Open |
| **R-006** | **New to this edition:** the FastAPI↔Next.js session-cookie bridging (§9.1, A-006) depends on a specific deploy topology (shared origin via reverse proxy). If infrastructure can't guarantee that topology, auth breaks in a way the reference implementation never had to solve (Next.js and its API routes were always same-origin by construction). | Technical | Medium | High | Confirm the deploy topology during infrastructure planning, before the auth module is built; have the token-based fallback design (§9.1 design note) ready if needed. | Platform / Infrastructure | Open — **new risk, not present in the reference PRD** |
| **R-007** | **New to this edition:** re-implementing the Prisma schema in SQLAlchemy/Alembic by hand risks subtle drift from the reference schema's constraints (unique indexes, nullability, default values), which could silently break the frontend's data assumptions since components are being reused as-is. | Technical | Medium | Medium | Treat `docs/prd/agentrise-harness-adoption-platform.md` §8.4 (and the underlying `prisma/schema.prisma` if accessible for reference) as the acceptance spec for the SQLAlchemy models; write a schema-diff check as part of this build's own validation gate. | Engineering Lead | Open — **new risk, not present in the reference PRD** |

---

## 13. Release Strategy

### 13.1 Launch Approach

This is a new build, starting from zero (unlike the reference implementation, which was already substantially built when its PRD was written). {TBD} — define launch approach before development begins.

### 13.2 Rollout Plan

| Phase | Audience | % Traffic | Entry Criteria | Exit Criteria |
|-------|----------|-----------|---------------|---------------|
| Alpha | Internal, dogfooding this build's own activity (mirroring the reference implementation's `harness-self` pattern) | 100% internal | Backend + frontend + MCP server all running against a seeded local DB | Core FR-OV/FR-PD flows verified end to end |
| Beta | {TBD} | {TBD}% | {TBD} | {TBD} |
| GA | All personas across all programs | 100% | Feature parity with the reference implementation's Must-Have set (§6.1) confirmed | — |

### 13.3 Rollback Plan

{TBD} — same recommendation as the reference implementation: since the read path is entirely derived from rebuildable rollups, disabling the ingest routes (or revoking ingest tokens) without rolling back the read-side deploy is a low-risk rollback lever worth formalizing.

### 13.4 Support & Operations

{TBD} — same operational minimums as the reference implementation: monitoring for freshness-timestamp staleness, an on-call/support contact for RBAC or ingest-token issues, and ownership of the MCP server's uptime.

---

## 14. Timeline & Milestones

| Phase | Description | Target Date | Key Dependencies | Owner |
|-------|-------------|-------------|-----------------|-------|
| Discovery & Design | This PRD + ADR-0005 (Python backend decision) + ADR-0006 (auth-bridging decision, resolving A-006/R-006) | {TBD} | | {TBD} |
| Development | Scaffold via `/arh-init` → `/arh-scaffold`, then story-by-story implementation per `/arh-intake` decomposition of this PRD | {TBD} | This PRD | {TBD} |
| QA & Beta | Schema-diff validation against the reference implementation (R-007); RBAC parity test suite | {TBD} | | {TBD} |
| Launch | {TBD} | {TBD} | | {TBD} |

**Target Ship Date:** {TBD}

---

## 15. Open Questions

| ID | Question | Owner | Target Resolution | Status |
|----|----------|-------|------------------|--------|
| Q-001 | Should the open-aggregate RBAC model be tightened to membership-scoped access for this build specifically? (Carried over from the reference PRD, A-004, R-003.) | Product / Security | {TBD} | Open |
| Q-002 | Should ingestion move to a scheduled/cron pipeline for this build? (Carried over, FR-ING-11, R-002.) | Platform/DevEx | {TBD} | Open |
| Q-003 | What retention policy should apply to `usage_events`/session rows? (Carried over, R-001, NFR-014.) | Data Engineering / Legal | {TBD} | Open |
| Q-004 | Should ingest tokens support scoped roles/capabilities beyond program-id allowlisting? (Carried over, R-004.) | Security / Platform | {TBD} | Open |
| Q-005 | Is the current 4-role MAU/team taxonomy final? (Carried over, R-005.) | Product | {TBD} | Open |
| **Q-006** | **New to this edition:** is the shared-origin reverse-proxy deploy topology (A-006) confirmed for this build's actual infrastructure, or does the token-based auth-bridging fallback need to be designed instead? | Platform / Infrastructure | Before ADR-0006 is written | Open — **blocks §9.1 implementation** |
| **Q-007** | **New to this edition:** should the MCP server and the new FastAPI backend share a Python package (Pydantic schemas, DB models) given they're now the same language, or stay fully independent services as they are today? | Platform/DevEx | {TBD} | Open — non-blocking, an optimization question |

Decisions logged as they're made should go in this project's own `docs/stories/<id>.md` decision logs once story generation begins.

---

## Appendix

### A. Glossary

| Term | Definition |
|------|-----------|
| AI SDLC | Use of AI tooling (Claude Code `/arh-*` commands, Copilot) within the software development lifecycle. |
| Program | A logical delivery initiative (e.g., Payments & Billing) with a type: Greenfield, Brownfield, Upgradation, Migration, or Maintenance. |
| Token consumption | Volume of AI tokens consumed by AI-assisted activity; reported in M/K; a proxy for AI usage intensity and cost. |
| Usage event | One row in the `usage_events` ledger — a single command invocation with its duration, tokens, and outcome. The raw source of truth for every rollup. |
| Rollup / rollup rebuild | A pre-aggregated table (org/program/user level) derived deterministically from `usage_events`; fully recomputed, never patched, on every successful ingest write. |
| MCP (Model Context Protocol) | The protocol `services/mcp-server` speaks; exposes `push_activity`/`push_artifacts` as callable tools over streamable HTTP. |
| Ingest token | A `hrn_pat_...` bearer credential (hashed at rest in `ingest_tokens`) authorizing a machine client to write to `/api/ingest/*` for a scoped set of program ids (or `"*"`). |
| Persona resolver | The 3-tier (env → config file → Postgres), 5-minute-cached component that maps an IdP `role` claim to one of the 5 personas. |
| Open-aggregate model | The RBAC design in which the program-visibility check grants any authenticated user access to any program's aggregate (non-individual) data. |
| Governance-eligible persona | One of `architect`, `product-manager`, `developer` — the only personas the governance-visibility check allows through. |
| Artifact | A generated output tracked per program: PRD, User story, Test case, Architecture diagram, API specification. |
| Guardrail | A governance control applied to a program (e.g., PII redaction, secret scanning), status `Enforced`/`Warning`/`NotImplemented`. |
| Organization Constitution | The non-negotiable rules/constraints/best-practices/vision governing AI usage org-wide, in 4 categories. |
| Adoption % | Share of the org's total programs classified "adopted" (≥1 repo with Harness installed). |
| Freshness timestamp | `system_metadata.last_successful_run_at`, surfaced on every dashboard view as the as-of time for the data shown. |
| Open-aggregate choke point | The single RBAC function (`backend/app/core/rbac.py`'s program-visibility check) that would need to change if Q-001/A-004/R-003 is ever resolved toward membership-scoping. |

### B. Technology Mapping (Reference Implementation → This Edition)

| Concern | Reference implementation (Next.js) | This edition (Python backend) |
|---|---|---|
| Backend framework | Next.js Route Handlers (`src/app/api/**/route.ts`) | FastAPI routers (`backend/app/routers/*.py`) |
| ORM / migrations | Prisma (`prisma/schema.prisma`, `prisma migrate`) | SQLAlchemy 2.0 (async) + Alembic |
| Auth | NextAuth.js (`KeycloakProvider`, `CredentialsProvider` for dev-bypass) | Authlib OIDC client inside FastAPI; a dev-bypass dependency override |
| Session | NextAuth JWT session | FastAPI-issued session cookie (httpOnly) |
| RBAC layer | `src/lib/rbac.ts`, `src/lib/persona-resolver.ts` | `backend/app/core/rbac.py`, `backend/app/core/persona_resolver.py` |
| Ingest auth | `src/lib/ingest/auth.ts` (`verifyBearer`, `canWriteProgram`) | `backend/app/auth/ingest_token.py` |
| Ingest validation/transform | `src/lib/ingest/validate.ts`, `src/lib/ingest/activity.ts` | `backend/app/services/ingest.py` (Pydantic schemas for validation) |
| Token-minting CLI | `scripts/mint-ingest-token.ts` (`pnpm mint-ingest-token`) | `backend/app/cli/mint_ingest_token.py` (Typer CLI) |
| Manual batch ingester | `scripts/ingest.ts` (`pnpm ingest`) | `backend/app/cli/ingest.py` |
| Role-sync CLI | `scripts/sync-user-roles.ts` (`pnpm sync:roles`) | `backend/app/cli/sync_user_roles.py` |
| Seed data | `prisma/seed.ts`, `src/fixtures/harness-events.ts` | `backend/app/cli/seed.py` + a Python fixtures module, reproducing the same shape/scale |
| System-metadata seed | `scripts/seed-system-metadata.ts` | Folded into the seed CLI above, or a dedicated `backend/app/cli/seed_system_metadata.py` |
| Freshness accessor | `src/lib/freshness.ts` | `backend/app/services/freshness.py` |
| Logging | Pino (structured JSON) | `structlog` or stdlib `logging` with a JSON formatter |
| GitHub repo-scan | `src/lib/github/repo-scan.ts` | `backend/app/services/repo_scan.py` (async HTTP client, e.g. `httpx`) |
| Frontend framework | Next.js (App Router), TypeScript | **Unchanged** — Next.js (App Router), TypeScript |
| Charting | `recharts` v2.x | **Unchanged** |
| Frontend data access | Server Components calling Prisma/route handlers directly, in-process | Client-side/Server Component fetches to the FastAPI backend over HTTP, cross-process |
| MCP server | `services/mcp-server` (Python, FastMCP) | **Unchanged** |
| Activity hooks | `.github/hooks/copilot-activity.mjs`, `harness-mcp-push.mjs` | **Unchanged** — these target the MCP server, not the main backend |
| Local Postgres (dev) | `docker-compose.yaml`, Postgres 16, host port 5433 | Same approach; compose file adds a `backend` service alongside `postgres` |
| Package management | pnpm (single workspace) | pnpm (`frontend/`) + Poetry or `uv` (`backend/`) |
| Tests | Vitest (unit) + Playwright (E2E) | Vitest (frontend unit, unchanged) + pytest (backend unit) + Playwright (E2E, unchanged, now exercising two services) |

### C. References & Source Documents

| Document | Location | Notes |
|----------|----------|-------|
| Reference PRD (Next.js, as-built) | `docs/prd/agentrise-harness-adoption-platform.md` | Source of truth for all product behavior in this document; this PRD is a derivation, not independent research. |
| Prior aspirational draft | `docs/prd/ai-sdlc-adoption-dashboards.md` | Historical context only; superseded by the reference PRD above. |
| SQLAlchemy schema (this edition, to be authored) | `backend/app/models/*.py`, `backend/alembic/versions/` | Canonical data model for this edition — 17 models re-expressed from Prisma per §8.4; treat the reference implementation's `prisma/schema.prisma` as the acceptance spec (R-007). |
| Auth / RBAC source (this edition, to be authored) | `backend/app/core/rbac.py`, `backend/app/core/persona_resolver.py`, `backend/app/auth/oidc.py` | Source for §9.1, §6 FR-AUTH-*; Python equivalents of the reference implementation's `src/lib/auth.ts`, `src/lib/rbac.ts`, `src/lib/persona-resolver.ts`. |
| MCP server | `services/mcp-server/src/agentrise_mcp/` | Carried over unchanged from the reference implementation; source for §6 FR-ING-01..03. |
| Ingest API + shared transform (this edition, to be authored) | `backend/app/routers/ingest.py`, `backend/app/services/ingest.py` | Source for §6 FR-ING-04..08; Python equivalents of the reference implementation's `src/app/api/ingest/*/route.ts`, `src/lib/ingest/activity.ts`, `src/lib/ingest/auth.ts`, `src/lib/ingest/validate.ts`. |
| Activity hooks | `.github/hooks/copilot-activity.mjs`, `.github/hooks/harness-mcp-push.mjs` | Carried over unchanged from the reference implementation; source for §6 FR-ING-07. |
| ADR-0001 (tech stack, reference implementation) | `docs/adr/0001-tech-stack.md` | Documents the single Next.js app, TypeScript, pnpm, Vitest+Playwright decision this edition deliberately departs from on the backend only. |
| ADR-0002 (system architecture, reference implementation) | `docs/adr/0002-system-architecture.md` | Documents the Postgres system of record, BFF via Route Handlers, batch ingestion, SSO/RBAC, Pino logging decisions this edition re-implements in FastAPI/structlog. |
| ADR-0003 (RBAC architecture, reference implementation) | `docs/adr/0003-bed-05-rbac-architecture.md` | 3-tier `PersonaResolver`, `IDP_PROGRAM_GROUP_PREFIX`, fire-and-forget audit logging — reproduced by this edition's `backend/app/core/persona_resolver.py`. |
| ADR-0004 (charting library, reference implementation) | `docs/adr/0004-charting-library-recharts.md` | recharts vs. alternatives, wrapper-isolation rationale — unchanged, since the frontend is carried over as-is. |
| ADR-0005 (Python backend decision, this edition — to be written) | `docs/adr/0005-python-backend.md` (not yet written) | Should record the FastAPI/SQLAlchemy/Authlib decision and the alternatives in §4.4. |
| ADR-0006 (auth-bridging pattern, this edition — to be written) | `docs/adr/0006-auth-bridging.md` (not yet written) | Should record the resolution of Q-006/A-006 — shared-origin cookie bridging vs. token-based bridging. |
| Seed fixtures (this edition, to be authored) | `backend/app/cli/seed.py` + a Python fixtures module (per Appendix B) | Should reproduce the baseline figures in §1.4, §11.2 identically to the reference implementation's `prisma/seed.ts`, `src/fixtures/harness-events.ts`, `scripts/seed-system-metadata.ts`. |

### D. Competitive Landscape

| Competitor / Alternative | Current Approach | Our Differentiation |
|-------------------------|-----------------|---------------------|
| Generic BI/dashboarding tools (Tableau, Power BI, Looker) pointed at a raw event table | Require significant custom modeling for personas, RBAC, guardrails/constitution concepts; typically licensed per-seat; no built-in ingestion contract for local developer-tool activity | Purpose-built persona dashboards and domain model native to AgentRise Harness, with RBAC baked in and a first-party MCP ingestion pipeline that captures local Claude Code/Copilot session detail no generic BI connector would know to look for |
| Ad-hoc log inspection / manually assembled spreadsheets | Slow, inconsistent, not self-service, no rollup layer | Self-service ingestion (mint a token → MCP push), consistent figures computed once server-side and reused across all five dashboards |
| Keep the reference implementation's Next.js-only stack (no backend split) | Single-language stack, but the ingestion pipeline (MCP server) is already Python, splitting operational knowledge across two ecosystems anyway | A Python backend converges the main API and the MCP server onto one language/toolchain, at the cost of the two-service auth-bridging complexity this PRD calls out in §9.1/R-006 |

### E. Out-of-Scope Feature Register

> Full record of features requested and deliberately excluded, with rationale. Input for future roadmap planning.

| Feature | Requested By | Reason Not In Scope | Revisit |
|---------|-------------|--------------------|---------|
| Browser-based creation/editing of program, constitution, or guardrail data | Reference PRD v2.0 (carried forward) | Read-only reporting layer by design; write surface is machine-only (ingest API) | {TBD} |
| User administration and provisioning inside the dashboard | Reference PRD v2.0 (carried forward) | Handled by Keycloak/IAM; the role-sync CLI only mirrors, never creates | {TBD} |
| Configuration or enforcement of the underlying AI tooling/guardrails | Reference PRD v2.0 (carried forward) | Dashboard reports status; does not enforce controls | {TBD} |
| PDF/CSV export of any view | Reference PRD v2.0 (carried forward) | Not implemented in the reference implementation; not required for this version either | {TBD} |
| Automated/scheduled ingestion (cron) | Reference PRD v2.0 (carried forward) | Manually triggered for this version; tracked as FR-ING-11 (Could Have) | Next version |
| Rewriting the frontend framework (e.g., to a full-Python UI) | This edition's own scope decision (§2.3) | Explicitly out of scope — this PRD only changes the backend; a frontend rewrite is a separate, larger decision | {TBD} |
| Token-based (non-cookie) auth bridging between frontend and backend | This edition's own scope decision (§9.1 design note) | Deferred unless A-006 is invalidated by the actual deploy topology (see Q-006) | Conditional — only if Q-006 resolves against the shared-origin assumption |

