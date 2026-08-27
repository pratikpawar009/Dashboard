# services/api

FastAPI backend. See root [README.md](../../README.md) for getting-started commands.

## Database setup

Run migrations before the first API boot:

```bash
cd services/api && uv run alembic upgrade head
```

Connection string is read from `DATABASE_URL` (`.env`, see `.env.example`), sourced via `app.core.config.Settings.database_url`. Default local value:

```
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/dashboard
```

Only start `uvicorn app.main:app` after migrations are applied.
