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

FastAPI's generated OpenAPI docs (`/docs`) cover every route in full; this table is a quick orientation for the `/auth/*` surface added by AUTH-01.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/auth/login` | none | 302 redirect to the Keycloak authorization endpoint; 501 if OIDC config is incomplete |
| GET | `/auth/callback` | query: `code` (required), `state` (optional) | 200 `{access_token, refresh_token, expires_in}`; 501 if OIDC config is incomplete; 401 on a failed code exchange |
| POST | `/auth/refresh` | body: `{refresh_token}` | 200 `{access_token, refresh_token, expires_in}`; 401 on any IdP-reported failure; 501 if OIDC config is incomplete |
| POST | `/auth/dev-bypass` | body: `{role?, email?, programs?}` (all optional) | 200 `{access_token, refresh_token, expires_in}` |

`/auth/dev-bypass` only exists — is registered at all — when `ENVIRONMENT` resolves to one of `local`, `development`, `dev`, `test`, `ci`; every other value, including `production`, `prod`, `staging`, and any typo, gets a `404` because the route was never registered. This is fail-closed by allow-list, not a "disabled in production" deny-check — nothing named `production` needs to be checked for it to be unreachable. In an allow-listed environment a dev-bypass token is fully usable against protected routes (it's signed by an ephemeral, process-local key that the JWKS cache resolves only there) — that's the point of the feature — but it is never usable outside one, by design.

## Environment variables

New in AUTH-01 (`services/api/.env.example`):

| Name | Default | Notes |
|---|---|---|
| `OIDC_CLIENT_ID` | `None` (unset) | Optional. |
| `OIDC_CLIENT_SECRET` | `None` (unset) | Optional. Env/secret store only — never commit a real value. |
| `OIDC_ISSUER` | `None` (unset) | Optional, e.g. `https://lab.apexonlab.com/apexonlogin/realms/Apexon`. |
| `OIDC_REALM` | `None` (unset) | Optional. |
| `OIDC_SCOPE` | `openid profile email groups` | |
| `PROGRAM_GROUP_PREFIX` | `program-` | A `groups` claim entry starting with this prefix becomes a program-membership entry (remainder after the prefix); non-matching entries are dropped from the parsed list but stay in the raw `groups` claim. |
| `CORS_ORIGINS` | `[]` (no origins allowed) | A single origin, or a comma-separated list of origins — not a JSON array. |

`OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` / `OIDC_ISSUER` together are the feature flag: while any one is unset, `/auth/login` and `/auth/callback` return `501` and only `/auth/dev-bypass` is reachable; set all three to go live against Keycloak, unset any one to back out without a redeploy.
