/**
 * Frontend FastAPI base URL (T-07, PGD-01).
 *
 * First consumer of `NEXT_PUBLIC_API_URL` anywhere in `apps/web` -- already
 * declared, unused, in `docker-compose.yml`. Falls back to
 * `http://localhost:8000`, matching `docs/config/stack-smoke.md`'s
 * `fastapi-2`/`fastapi` `Run:` port.
 */
export function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}
