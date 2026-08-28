# Dev-bypass sign-in, and pointing at the real Apexon realm

`docs/how-to/` did not exist before this file — created for it (no sibling structure to match yet).

For the `/auth/*` route table and env-var defaults, see the root [README.md](../../README.md#api). For the boot-with-Keycloak summary and a one-line curl recipe, see [`services/api/README.md`](../../services/api/README.md#auth). This file is the deeper walkthrough both point to.

## 1. Sign in locally, no Keycloak at all

```bash
cd services/api
ENVIRONMENT=local uv run uvicorn app.main:app --reload --port 8000
```

`ENVIRONMENT` must resolve (lowercased) to one of `local`, `development`, `dev`, `test`, `ci` — see § 3 below. `.env.example`'s default (`ENVIRONMENT=development`) already qualifies, so a plain `cp .env.example .env` also works.

Mint a token:

```bash
curl -s -X POST http://localhost:8000/auth/dev-bypass \
  -H "Content-Type: application/json" \
  -d '{}'
# -> {"access_token": "<jwt>", "refresh_token": "<jwt>", "expires_in": 3600}
```

`role`, `email`, `programs` are optional overrides (defaults: `role="developer"`, `email="dev-bypass@local"`, `programs=[]`). No field contacts Keycloak — this route makes zero outbound calls.

Use the token as a bearer credential on an authenticated route:

```bash
curl -s http://localhost:8000/<protected-route> \
  -H "Authorization: Bearer <access_token>"
```

AUTH-01 ships the verification dependency (`app/core/auth.py::get_current_user`) but no route calls `Depends(get_current_user)` yet — that starts with AUTH-02/03/04. There is nothing to point the second curl at today; the recipe above is what to run once one exists.

### Role / programs override recipe

```bash
curl -s -X POST http://localhost:8000/auth/dev-bypass \
  -H "Content-Type: application/json" \
  -d '{"role": "admin", "email": "dev@example.com", "programs": ["alpha"]}'
```

`programs: ["alpha"]` is encoded into the token's `groups` claim as `["program-alpha"]` (`program_group_prefix`, default `"program-"`). On the verification side, `get_current_user` parses it back: any `groups` entry starting with the prefix has the prefix stripped into `CurrentUser.programs`; the raw entry stays in `CurrentUser.groups` unchanged. Verified directly against the shipped code:

```
>>> _parse_programs(["program-alpha"], "program-")
['alpha']
```

So `programs: ["alpha"]` in the request becomes `groups: ["program-alpha"]` in the token and back to `programs: ["alpha"]` in the session — `groups` and `programs` are two different lists on `CurrentUser`, not one field renamed.

## 2. Two things you WILL hit — read this before you file a bug

The dev-bypass signing key is a process-local, ephemeral RSA keypair, generated once per process and never persisted (`app/auth/jwks.py`, decision D-08). Two direct consequences:

- **A token dies the moment its process does — including a `--reload` reload.** `uvicorn --reload` restarts the worker process on every file save, which generates a *fresh* keypair. A token minted before the reload 401s afterward, with no correctness bug behind it. Verified: a token signed in one process fails `authlib.jose.jwt` verification (`BadSignatureError`) against a second process's public key, because the two processes never share a private key.
- **A multi-worker run gives each worker its own key.** If the API is ever started with `uvicorn --workers N` or under gunicorn, each worker generates its own keypair independently. A token minted by whichever worker served your `/auth/dev-bypass` call will 401 on any other worker that later serves your authenticated request. The shipped `Dockerfile` runs a single worker with no `--workers` flag, so this does not bite local Docker/compose use — only a deliberately multi-worker local setup.

Neither is a bug to fix — it's the direct cost of never persisting or committing a real signing key (the rejected alternative in D-08). If a request 401s right after it worked a minute ago, re-mint the token before debugging anything else.

## 3. Why `/auth/dev-bypass` sometimes 404s

The route is registered at all only when the normalized `ENVIRONMENT` is a member of the allow-list `{local, development, dev, test, ci}` (`app/core/config.py::NON_PRODUCTION_ENVIRONMENTS`). Every other value — `production`, `prod`, `staging`, or a typo like `produciton` — leaves the router unregistered in `app/main.py::create_app`, so FastAPI's own routing returns `404` before any handler code runs. Verified: `ENVIRONMENT=staging` boots the app fine (`/health` returns 200) but `/auth/dev-bypass` 404s.

This is a security property, not a "disabled in production" feature switch: an allow-list denies every value it doesn't explicitly name, so an unanticipated environment name is unreachable by default. The rejected alternative — `environment != "production"` — fails open on exactly the values above (`"prod"` still reads as "not production"). See `DECISIONS.md` § D-01.

## 4. Pointing at the real `Apexon` realm for pilot testing

This is what PLAN.md §6 leans on to accept risk R-09 (no `keycloak` service in `docker-compose.yml`): pilot validation runs against the real lab realm, not a local container. There is no shortcut around that — this path needs the real realm and a client registered in it.

**The three vars that flip the feature on.** `Settings.oidc_configured` is `True` only when all three are non-empty:

| Var | Value for the `Apexon` realm |
|---|---|
| `OIDC_CLIENT_ID` | the client id registered in Keycloak (e.g. `dashboard-api`) |
| `OIDC_CLIENT_SECRET` | from the Keycloak client's **Credentials** tab — never commit it |
| `OIDC_ISSUER` | `https://lab.apexonlab.com/apexonlogin/realms/Apexon` |

While any one is unset, `/auth/login`, `/auth/callback`, `/auth/refresh` return `501` (`{"error":{"code":"http_501","message":"oidc_not_configured","details":null}}` — verified) and only `/auth/dev-bypass` is reachable. `services/api/.env.example` ships `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` **empty on purpose** — not as a placeholder string — so a plain `cp .env.example .env` reproduces this default-disabled state rather than silently becoming "configured" with junk credentials (AF-12). `OIDC_ISSUER` ships with the real, non-secret issuer URL already filled in; it's harmless alone because `oidc_configured` requires all three.

**The flow, once configured:**

1. `GET /auth/login` — 302-redirects the browser to Keycloak's authorization endpoint (`{issuer}/protocol/openid-connect/auth`) with `client_id`, a dynamically-derived `redirect_uri`, `response_type=code`, `scope`, and a per-request `state`.
2. User authenticates against the `Apexon` realm in Keycloak.
3. Keycloak redirects back to `GET /auth/callback?code=...&state=...`. The handler exchanges `code` for tokens via a direct POST to Keycloak's token endpoint and returns `{access_token, refresh_token, expires_in}` — Keycloak's response passed through, no `Set-Cookie` ever set.
4. `POST /auth/refresh` with `{"refresh_token": "..."}` exchanges it for a new pair the same way; any non-2xx from Keycloak (expired/revoked token) maps to `401`, not a passthrough of Keycloak's raw status.

**What this path does NOT cover.** There is no Keycloak service in `docker-compose.yml` (accepted risk R-09, PLAN.md §6) — you cannot `docker compose up` your way into this flow. You need network access to `lab.apexonlab.com` and a client already registered in the `Apexon` realm with a redirect URI matching whatever host serves `/auth/callback` in your setup.

**Backing out.** Unset (not blank-string, actually remove or empty) any one of the three OIDC vars and restart the API — `/auth/login`/`/auth/callback`/`/auth/refresh` revert to `501` immediately, no redeploy, no code change (`REQUIREMENTS.md` § Rollout plan). Dev-bypass keeps working the whole time, independent of OIDC config.

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `POST /auth/dev-bypass` → `404` | `ENVIRONMENT` isn't in the allow-list (§ 3) — check for a typo or a value like `staging`/`production` | Set `ENVIRONMENT` to one of `local`, `development`, `dev`, `test`, `ci` and restart |
| `401 {"error":{"...","message":"invalid_token",...}}` on a token that worked a minute ago | The API process restarted (including a `--reload` reload) and generated a new signing key (§ 2, D-08) | Mint a fresh dev-bypass token against the currently-running process |
| `501 {"...","message":"oidc_not_configured",...}` on `/auth/login`, `/auth/callback`, or `/auth/refresh` | `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` / `OIDC_ISSUER` — at least one is unset or empty | Fill all three (§ 4); a plain `cp .env.example .env` leaves them unconfigured by design |
| Keycloak reports a `redirect_uri` mismatch | `/auth/login` derives the callback URL from the incoming request (`request.url_for`) rather than a configured `oidc_redirect_uri` setting — it won't match Keycloak's registered URI behind a proxy/load balancer unless forwarded-host headers are trusted correctly | See `FLAGS.md` § AF-08; register the exact URI your deployment actually presents, or forward `X-Forwarded-Proto`/`Host` correctly |
