<!-- Reconciled by /arh-scaffold: manifests + Dockerfiles now exist at
apps/web (nextjs) + services/api (fastapi-2) per ADR-0001. Docker: rows below
point at docker-compose.yml (root) which wires web + api + postgres. One
section per stack id recorded in docs/adr/0001-tech-stack.md § Decision. -->

# fastapi

Generic repo-wide tag (paths: `**`) for the same backend service concretely
declared as `fastapi-2` (paths: `services/api/**`, uv, pytest). Same process —
see that section for the authoritative commands.

- Deps: docker run --rm -d --name dashboard-postgres -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=dashboard postgres:16
- Migrate: cd services/api && uv run alembic upgrade head
- Run: cd services/api && uv run uvicorn app.main:app --reload --port 8000
- Docker: docker compose up api postgres
- Check: http://127.0.0.1:8000/health

# typescript

- Run: (n/a — type system only, no standalone process; enforced via nextjs stack's typecheck)
- Docker: (n/a — same reason)

# next

Generic repo-wide tag (paths: `**`) for the same frontend app concretely
declared as `nextjs` (paths: `apps/web/**`, pnpm, vitest, v15). Same process —
see that section for the authoritative commands.

- Deps: (n/a — talks to the backend over REST, no direct backing service)
- Run: cd apps/web && pnpm dev --port 3000
- Run: set NEXT_PUBLIC_API_URL=http://localhost:8000 in apps/web/.env.local (copied from apps/web/.env.example) before `pnpm dev`, or the Program Detail page cannot reach the backend locally
- Docker: docker compose up web
- Check: http://127.0.0.1:3000/

# postgres

- Run: (n/a — datastore, no application entrypoint)
- Docker: docker compose up postgres
- Check: pg_isready -h 127.0.0.1 -p 5432

# pytest

- Run: (n/a — test runner only, no standalone process; invoked via fastapi-2 stack's `test`/`test_unit` commands)
- Docker: (n/a — same reason)

# alembic

Migration tool, invoked as a step before the API runs (see `Migrate:` under
`fastapi-2`/`fastapi`), not a standalone process.

- Run: (n/a — see fastapi-2 § Migrate)
- Docker: (n/a — same reason)

# pydantic

- Run: (n/a — validation library only, no standalone process; exercised via fastapi-2 stack)
- Docker: (n/a — same reason)

# nextjs

- Deps: (n/a — talks to services/api over REST, no direct backing service)
- Run: cd apps/web && pnpm dev --port 3000
- Run: set NEXT_PUBLIC_API_URL=http://localhost:8000 in apps/web/.env.local (copied from apps/web/.env.example) before `pnpm dev`, or the Program Detail page cannot reach the backend locally
- Docker: docker compose up web
- Check: http://127.0.0.1:3000/

# fastapi-2

- Deps: docker run --rm -d --name dashboard-postgres -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=dashboard postgres:16
- Migrate: cd services/api && uv run alembic upgrade head
- Run: cd services/api && uv run uvicorn app.main:app --reload --port 8000
- Docker: docker compose up api postgres
- Check: http://127.0.0.1:8000/health
