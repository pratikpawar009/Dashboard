---
name: pytest-patterns
description: pytest patterns for this project — fill body with team conventions. Used by implementation/validation/arh-review agents.
when_to_use: Writing or reviewing pytest code.
user-invocable: false
allowed-tools: Read Write Edit Bash Grep Glob
---
# pytest Patterns

<!-- Harness scaffold: stack=pytest — STRUCTURE only; -->
<!-- Fill every CORE section below. Under OPTIONAL, keep only the sections that apply to -->
<!-- this stack and DELETE the heading+slot of the rest BEFORE filling. Keep ≤ 200 lines. -->
<!-- Deletion is safe: OPTIONAL slots use the word OPTIONAL (not TODO) so the lint does not -->
<!-- nag for them; CORE TODO slots are nagged until filled — that is intentional. -->
<!-- Loaded by implementation-, impl-planning-, validation-, code-review-, security-review-, -->
<!-- scaffold-, and cicd-agents when this stack is active. -->

## Verified facts

<!-- BEGIN VERIFIED FACTS -->
<!-- Owned by skill `deep-scan-verification` (/arh-init Phase 6) — `harness fill` never -->
<!-- edits between these markers. Empty until a brownfield deep scan approves facts here. -->
<!-- Each bullet ends in (see file:line); the file it cites is this fact's proof. -->
<!-- END VERIFIED FACTS -->

## Idioms

- Tests live under `services/api/tests/`, package-ified with `tests/__init__.py`; `testpaths = ["tests"]` is pinned in `pyproject.toml:39` — pytest only discovers here.
- Flat `test_<behavior>` functions, no test classes yet (`tests/test_smoke.py:1`, `def test_smoke():`).
- `pytest-asyncio` and `httpx` are installed dev dependencies (`pyproject.toml:20-21`) for testing the async FastAPI app, but the only existing test is a synchronous arithmetic smoke check (`tests/test_smoke.py:1-3`) — no route/app test exists yet.
- No `conftest.py` exists — no shared fixture (e.g. a `TestClient`/`AsyncClient` against `app.main.app`) is wired despite `httpx` being present as a dev dependency.
- `pyproject.toml`'s `[tool.pytest.ini_options]` sets only `testpaths` (`pyproject.toml:38-39`) — no `asyncio_mode` is configured, so any `async def test_...` must carry an explicit `@pytest.mark.asyncio` marker; pytest-asyncio's `auto` mode is not enabled.

## Project structure

- `services/api/tests/` mirrors `app/` only loosely so far — one flat `test_smoke.py`, no per-router test files yet (e.g. no `tests/api/test_activities.py`).
- `tests/__init__.py` makes the directory an importable package (present but empty beyond that role).

## Layering & dependency rules

- `tests/*` may import freely from `app.*` — it's the outermost layer.
- `app/*` must never import from `tests/*`.

## Error handling

No exception-path tests exist yet. When added, assert against the real error envelope from `app/core/errors.py:9-10` (`{"error": {"code", "message", "details"}}`), not an invented shape.

## Anti-patterns

- Assuming a `TestClient`/`AsyncClient` fixture already exists in `conftest.py` — it doesn't; add one (scoped in a new `conftest.py`) before writing the first real endpoint test, rather than duplicating client setup per test file.
- Writing tests outside `services/api/tests/` and expecting pytest to discover them — `testpaths` is pinned to `["tests"]` (`pyproject.toml:39`).
- Writing `async def test_...()` without `@pytest.mark.asyncio` — `asyncio_mode` is not set to `auto`, so the marker is required or the test silently doesn't run as a coroutine.
- Having a route test hit a live Postgres instance with no fixture/teardown — no such fixture exists yet; this is undecided, flag it rather than assuming a pattern.

## Examples

BAD — hitting a real running server instead of testing the ASGI app in-process:
```python
import requests
def test_activities():
    r = requests.get("http://localhost:8000/activities")
    assert r.status_code == 200
```

GOOD — async client against the app object, matching installed deps (httpx, pytest-asyncio) and app/api/health.py's route:
```python
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
```

## References

- `services/api/tests/test_smoke.py` — only existing test
- `services/api/pyproject.toml:18-24,38-39` — dev deps + pytest config
- `docs/config/project-commands.yaml` — `test`/`test_unit`: `cd services/api && uv run pytest`

## Dependency, build & CI

Dev deps: `pytest>=8.3`, `pytest-asyncio>=0.24`, `httpx>=0.27`, `ruff>=0.7`, `mypy>=1.13` (`pyproject.toml:18-24`), installed/locked via `uv` (`uv.lock`). Run with `uv run pytest` (`docs/config/project-commands.yaml`). No CI pipeline runs this yet (`CI: none` per `CLAUDE.md`) — tests are a local/preflight step only; `docs/config/project-commands.yaml`'s `preflight:` list does not yet include `uv run pytest`.
