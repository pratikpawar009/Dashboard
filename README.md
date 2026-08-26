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
