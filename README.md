# dashboard

AI SDLC monitoring dashboard. Next.js frontend, FastAPI backend, Postgres datastore. See `docs/adr/0001-tech-stack.md` and `docs/adr/0002-system-architecture.md` for decisions.

## Layout

- `apps/web` — Next.js 15 (TypeScript, pnpm, vitest)
- `services/api` — FastAPI 0.115 (Pydantic, Alembic, uv, pytest)
- `docker-compose.yml` — web + api + postgres, local orchestration

## Getting started

```bash
# frontend
cd apps/web && pnpm install && pnpm dev

# backend
cd services/api && uv sync && uv run uvicorn app.main:app --reload --port 8000

# or everything via Docker
docker compose up --build
```

Commands: `docs/config/project-commands.yaml`. Stack idioms: `.claude/skills/<framework>-patterns/SKILL.md`.

## API

FastAPI's generated OpenAPI docs (`/docs`) cover every route in full; this table is a quick orientation for the `/auth/*` surface added by AUTH-01, plus `/api/programs` (AUTH-04), `/api/overview/program-detail/{program_id}` (PGD-01), `/api/personal-usage/{user_id}` (SHP-02), `/api/ingest/manifest` (ING-10), and `/api/overview/summary` (OVW-01).

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/auth/login` | none | 302 redirect to the Keycloak authorization endpoint, carrying a single-use `state` and a PKCE `code_challenge` (S256); 501 if OIDC config is incomplete |
| GET | `/auth/callback` | query: `state` (required — must be one `/auth/login` issued), plus either `code` or the IdP's `error` | 200 `{access_token, refresh_token, expires_in}`; 501 if OIDC config is incomplete; 400 `invalid_state` if `state` is absent, unknown, already used, or expired; 400 `missing_code` if neither `code` nor `error` is present; 401 on a failed code exchange or any IdP-reported `error` |
| POST | `/auth/refresh` | body: `{refresh_token}` | 200 `{access_token, refresh_token, expires_in}`; 401 on any IdP-reported failure; 501 if OIDC config is incomplete |
| POST | `/auth/dev-bypass` | body: `{role?, email?, programs?}` (all optional) | 200 `{access_token, refresh_token, expires_in}` |
| GET | `/api/programs` | none (bearer token via the standard auth dependency) | 200 `{programs: [{program_id, label, href, dotStyle}]}` (ADR-0005 shape) — `cio` sees every program, every other persona is scoped to `session.programs`; 403 `Access denied` if persona resolution fails (fail-closed); 401 if the bearer token is missing or invalid. A `200` is not proof of program membership: `program_visibility` is an open-aggregate veto gate that passes for any authenticated session — the `WHERE program_id IN current_user.programs` clause does the actual scoping — so consumers must read `session.programs` directly rather than infer membership from a successful response |
| GET | `/api/overview/program-detail/{program_id}` | none (bearer token via the standard auth dependency) | 200 `{header, summary}` (ADR-0007 shape) — `header: {icon, name, type, description}`; `summary` is an ordered 7-entry `{glyph, value, label}` array, `glyph`/`label` fixed server-owned presentation constants, only `value` varies per program; the response is byte-identical across every persona — no persona branching, unlike `/api/programs`' `session.programs` scoping above, and `program_visibility` is called with the real `program_id` but still never filters by membership (this endpoint is intentionally unscoped); 404 `program not found` if `program_id` doesn't exist; 401 if the bearer token is missing or invalid |
| GET | `/api/personal-usage/{user_id}` | none besides the bearer token, plus optional `?range=7d\|30d\|90d` (default `30d`) | 200 `{cards, daily_tokens, commands}` (ADR-0009 shape) — `cards` is an ordered 4-entry `{glyph, value, label, iconBg, iconColor}` array, a to-date aggregate (never `delta`); `daily_tokens`/`commands` are range-scoped, correct simultaneously with `cards` since they answer different questions; `commands[].count` is a raw int, every other value pre-formatted; no `program_id` in request or response — "my usage" is a cross-program aggregate by contract, so PGD-05 reuses it verbatim and inherits the same org-wide scope; 403 with no data body on RBAC denial (`individual_usage_visibility`: self always, else `cio` only, logged as `individual_view_denied`); 400 `invalid_range` if `range` is outside `{7d,30d,90d}`; 401 if the bearer token is missing or invalid |
| POST | `/api/ingest/manifest` | body: `{programId, program:{name,type,description}, team:[{email,name,role,aliases[]}]}` — `programId` travels in the body, not the path; auth is a bearer **ingest token** (`ingest-token-auth`, ADR-0006), a wholly separate mechanism from the user bearer/session the rows above use, and the token is scoped to `allowed_program_ids` (or a `"*"` wildcard) | 200 `{identity, roster, roster_detail}` — two-tier validation: a malformed or unrecognized `program.type` aborts the *entire* request with `400` and writes nothing, whereas one bad `team[]` entry (unmapped `role` slug, malformed email) rejects only that entry while the identity write and every other valid entry still commit; every alias in a `team[]` entry's `aliases[]` gets its own roster row, since usage joins on `usage_events.user`, which carries whatever `git config user.email` was set to on the producing machine; a roster row absent from a re-push is soft-deleted (`removed_at`, never hard-deleted) and un-deleted if the email reappears; the roster lands in `program_roster`, **not** `program_members` — the latter is rebuilt from `usage_events` on every activity ingest and would silently wipe it (ADR-0010); 400 also on a non-JSON body or a missing `programId`; 401 `missing`/`unknown`/`revoked`/`expired` on the ingest token; 403 `scope` if the token's `allowed_program_ids` doesn't cover this `programId`; 413 if `team[]` exceeds 500 raw entries, counted before alias expansion |
| GET | `/api/overview/summary` | none (bearer token via the standard auth dependency) | 200 `{cards, programs_using_ai}` (DECISIONS.md D-01/D-02 shape) — `cards` is an ordered 5-entry `{glyph, value, label, sub}` array, *four* fields — unlike `/api/overview/program-detail`'s three-field `summary` card two rows above, which a reader might otherwise assume it matches; order is the contract. Card 1 (`programs_using_ai`) is the literal ratio `"{count} / {total}"`, exempt from `format_number()`, and the only card carrying a non-null `sub` (`"{pct}% adoption"`); cards 2–5 are `format_number()`-formatted with `sub: null`, and card 5 is a plain count despite its `_over_total` id. `programs_using_ai: {count, total, adoption_percent}` — `adoption_percent` is `null`, never `0.0`, when `total` is 0. No freshness timestamp is returned anywhere on the page — the freshness read exists only to fail loudly, not to be displayed; 403 with no data body for a non-cio persona (logged as `rbac_check_org_access`); 500 `"ingestion job may not have run yet"` when `system_metadata` has no `ingestion` row — this freshness read is unconditioned by the rollup lookup, so the 500 wins even when the rollup row is also absent, rather than degrading to the all-zero response; 401 if the bearer token is missing or invalid |

A roster pushed through `POST /api/ingest/manifest` does **not** take effect immediately for sessions already being served. `session.programs` is resolved from `program_roster` behind a per-worker, per-process cache with a `300s` TTL, and **TTL expiry is the only invalidating event** — the ingest endpoint deliberately signals nothing (no cross-worker coherence, no Redis). So a re-push becomes visible to an already-warm worker only after its own next expiry, up to `300s` later, and each worker expires on its own schedule. **An app restart is the only faster lever.** Budget for that when onboarding or removing someone in a hurry.

`/auth/dev-bypass` only exists — is registered at all — when `ENVIRONMENT` resolves to one of `local`, `development`, `dev`, `test`, `ci`; every other value, including `production`, `prod`, `staging`, and any typo, gets a `404` because the route was never registered. This is fail-closed by allow-list, not a "disabled in production" deny-check — nothing named `production` needs to be checked for it to be unreachable. In an allow-listed environment a dev-bypass token is fully usable against protected routes (it's signed by an ephemeral, process-local key that the JWKS cache resolves only there) — that's the point of the feature — but it is never usable outside one, by design.

`/login`, `/callback`, `/api/proxy/programs`, and `/api/proxy/program-detail/{program_id}` (AUTH-05) are Next.js Route Handlers in `apps/web`, not FastAPI routes — they will not show up in `/docs` above. The two `/api/proxy/*` routes are full server-to-server proxies: the browser never calls FastAPI directly through them, and no route hands an access token to client-side JavaScript (`docs/adr/0008-client-side-auth-route-handler-proxy.md`).

## Environment variables

New in AUTH-01 (`services/api/.env.example`), except `PERSONA_ROLE_MAP` and `PERSONA_CONFIG_FILE`, new in AUTH-02; `OIDC_REDIRECT_URI`, new in AUTH-05; and `NEXT_PUBLIC_API_URL`, new in PGD-01 (`apps/web/.env.example` — the first `apps/web` env var; every other row below is `services/api/.env.example`):

| Name | Default | Notes |
|---|---|---|
| `OIDC_CLIENT_ID` | `None` (unset) | Optional. |
| `OIDC_CLIENT_SECRET` | `None` (unset) | Optional. Env/secret store only — never commit a real value. |
| `OIDC_ISSUER` | `None` (unset) | Optional, e.g. `https://lab.apexonlab.com/apexonlogin/realms/Apexon`. |
| `OIDC_REALM` | `None` (unset) | Optional. |
| `OIDC_REDIRECT_URI` | `http://localhost:3000/callback` | The frontend's own `/callback` route (AUTH-05) — Keycloak must send the browser here, not to FastAPI, so the frontend can write the `dashboard_session` cookie. Left empty, `_resolve_redirect_uri` (`services/api/app/auth/oidc.py:84`) falls back to deriving the API's own `/auth/callback` from the incoming request, so Keycloak returns the browser to FastAPI instead of Next.js and the session cookie is never written. |
| `OIDC_SCOPE` | `openid profile email` | Every scope must exist on the realm — Keycloak rejects the whole authorization request with `invalid_scope` otherwise. `groups` is deliberately not requested (AUTH-06): program membership comes from `program_roster`, not the IdP. A deployment that relies on `groups` for some *other* purpose must add it back to its own value here — and supply the client scope for it, since `groups` is not a Keycloak default. `CurrentUser.groups` still populates verbatim whenever Keycloak sends it; it simply no longer feeds `programs`. |
| `CORS_ORIGINS` | `[]` (no origins allowed) | A single origin, or a comma-separated list of origins — not a JSON array. |
| `PERSONA_ROLE_MAP` | `None` (unset) | Optional. Tier-1 override for persona resolution: a JSON object mapping an IdP role claim to one of the five personas (`cio`, `architect`, `developer`, `product-manager`, `engineering-manager`), e.g. `{"cio":"cio","admin":"cio"}`. Resolution order is Tier-1 (this var) → Tier-2 YAML (`services/api/config/persona_role_map.yaml`, requires an app restart to pick up changes — no hot-reload) → Tier-3 Postgres `persona_config` (system of record). Unset means Tier-1 is empty, not an error. Invalid JSON, a non-object value, or an object with non-string values are also treated as empty — a `persona_role_map_parse_error` warning is logged and resolution falls through to Tier-2/3; this fail-open parse behaviour is distinct from an unmapped role, which still raises once all three tiers come up empty. |
| `PERSONA_CONFIG_FILE` | `None` (unset) | Optional. Tier-2 YAML path override. Unset, the resolver uses its own `__file__`-anchored default (`services/api/config/persona_role_map.yaml`), independent of process cwd. |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | `apps/web/.env.example`, not `services/api/.env.example`. The frontend's FastAPI base URL, used for both the Program Detail page's server-rendered initial fetch and the client-side program-switcher reload. |

## Keycloak client requirements

The API is a confidential, PKCE-enforcing client. Its Keycloak client must have:

- **Client authentication** ON (the code exchange sends `client_secret`).
- **Valid redirect URIs** containing the API's own callback — `http://localhost:8000/auth/callback` locally. A frontend-style URI (`.../api/auth/callback/keycloak`) is not interchangeable: this integration exchanges the code server-side, so the browser must be sent back to the API.
- An **additional** Valid Redirect URI for the frontend's own callback — `http://localhost:3000/callback` locally (AUTH-05, `OIDC_REDIRECT_URI`). This extends the bullet above, it does not replace it: the browser now lands on the frontend's callback first, but the API still exchanges the code server-side, so both URIs must stay registered.

PKCE (S256) is sent on every authorization request per OAuth 2.1, so a client with *Proof Key for Code Exchange* required works as-is.

No Keycloak **group** is required for any program. Program membership is read from `program_roster` (AUTH-06), populated from each program's own committed roster file via `POST /api/ingest/manifest` — onboarding a program's dashboard access is a roster file change, never realm administration.

`OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` / `OIDC_ISSUER` together are the feature flag: while any one is unset, `/auth/login` and `/auth/callback` return `501` and only `/auth/dev-bypass` is reachable; set all three to go live against Keycloak, unset any one to back out without a redeploy.
