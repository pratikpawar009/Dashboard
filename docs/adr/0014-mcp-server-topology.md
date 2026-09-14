# ADR-0014 — MCP server deployment topology

- Status: Accepted
- Date: 2026-09-14
- Deciders: Pratik Pawar (PO+Architect, single-approver mode)
- Story: ING-04 · Decision: DECISIONS.md D-01

## Context

`services/mcp-server/` exists so Claude Code and other MCP-capable clients on a developer's laptop can push AI-SDLC activity (`push_activity`) and governance artifact counts (`push_artifacts`) into the dashboard's already-shipped ingest API (`POST /api/ingest/{kind}`, ADR-0013). The MCP server is a headless local Python process; the developer's workstation is its deploy target (ING-04 REQUIREMENTS FR-1). The FastAPI backend under `services/api/` is the only server component the browser and existing CI jobs talk to; it has shipped for eleven prior stories with its own dependency graph, its own `docs/config/project-commands.yaml preflight:` block, and its own release pipeline.

The topology question is which relationship the two services have. Option (a) — fold the mcp-server into `services/api/` as a subpackage or ASGI mount — reuses the API's virtualenv, its preflight, and its deploy pipeline. Option (b) — ship the mcp-server as a sibling package with its own `pyproject.toml`, own venv, own deploy — keeps the API's boot surface unchanged and lets the mcp-server iterate on the MCP transport (`fastmcp` v2.x, D-02) without triggering main-API deploys. The choice is system-level because ING-05 (Copilot-Chat bridge) will describe its host runtime relative to this decision, and because the ingest contract between the two services is HTTP-only under (b) — a stable seam that the review gate is already positioned to police (AF-02).

## Decision

`services/mcp-server/` ships as a separately-deployed sibling service to `services/api/`. Concretely:

- Own `pyproject.toml`, own dependency set (`fastmcp>=2,<3`, `httpx`, `pyyaml`). No dependency shared with `services/api/`.
- Own Python virtualenv under `services/mcp-server/.venv`. `services/api/.venv` is never activated by any mcp-server command.
- Own deployment pipeline / install path (`pip install agentrise-mcp` or the built wheel). Own console script `agentrise-mcp` and module entry `python -m agentrise_mcp`.
- **NOT** wired into `services/api/`'s preflight, bootstrap, or pytest run. A break in `fastmcp` or its streamable-HTTP transport never blocks a backend PR.
- Root `docs/config/project-commands.yaml` receives no `mcp_server:*` namespace (D-07). Adding one without wiring it into `preflight` would produce dead keys; wiring it in would defeat this ADR.
- `docs/config/stack-smoke.md` gains one `# mcp-server` section (D-07, F-45) documenting the sibling service's boot for out-of-band ops smoke checks — `Run:`, `Env:`, `Check:` bullets, no `Deps:` (no DB), no `Migrate:` (no schema).
- Communicates with the main API over HTTP only, against the frozen `POST /api/ingest/activity` + `POST /api/ingest/artifacts` contract (ADR-0013, D-03). No in-process import of the API's application object; no shared Python module boundary.

## Consequences

**Positive**

- Isolated blast radius. A break in `fastmcp`, its transport, or any mcp-server dep never affects the FastAPI API's boot. The API's preflight stays deterministic across ING-05+ additions.
- Independent release cadence. MCP tools iterate without triggering main-API deploys; the API iterates without republishing the mcp-server wheel.
- Straightforward client packaging. `pip install agentrise-mcp` (or a built wheel) works without pulling in FastAPI, SQLAlchemy, Alembic, or Keycloak's Authlib.
- Auth boundary enforced end-to-end. The mcp-server process sees only its own env vars (`AGENTRISE_INGEST_TOKEN`, D-06); token discipline (R-07 carry-forward) stays clean because the two services never share a process address space.
- HTTP-only contract is greppable and reviewable. A drift between what the mcp-server POSTs and what the API accepts (AF-02) shows up as a diff against the ADR-0013 endpoint contract, and the review gate is already positioned to catch it.

**Negative**

- Two deploy targets to keep in sync during a contract change. A change to `POST /api/ingest/{kind}`'s envelope shape needs coordinated releases of the API and the mcp-server (mitigated by ADR-0013's generic-kind router — new kinds are purely additive to `_ACCEPTED_KINDS`).
- Two-way HTTP dep on `/api/ingest/*` is real coupling. Contract drift (AF-02) is a live risk and stays on the review gate rather than being caught by the compiler.
- Duplicate infra concerns (logging, retries, health checks) between the two services. Accepted for now; may consolidate into a shared internal lib later if a third sibling service materialises.

**Reversible?**

Medium. Reverting means: (i) collapsing `services/mcp-server/pyproject.toml` into `services/api/pyproject.toml`'s `[project.optional-dependencies]`, (ii) exposing the two tools through an ASGI mount under the API's app object, (iii) merging the two virtualenvs, (iv) deleting the mcp-server `.venv` and the `# mcp-server` section in `docs/config/stack-smoke.md`. No data migrated under this choice; no persistent state depends on the topology.

## Alternatives considered

1. **Wire mcp-server into `services/api/` as a subpackage.** Rejected — couples the MCP transport (`fastmcp`) to the API's dependency graph, doubles the API's boot surface, and forces the mcp-server to share the API's release cadence and pytest run. Every backend PR would pay the mcp-tool test cost.
2. **Run mcp-server in-process with the API via ASGI mount.** Rejected — same coupling risk as (1); additionally, `fastmcp`'s streamable-HTTP lifecycle would sit under the API's `uvicorn`/`gunicorn` worker model, complicating the API's worker tuning and making the MCP transport a boot-order concern for backend deploys.
3. **Run mcp-server as a separately-deployed sibling (this ADR).** Accepted. Trades one extra deploy target and an HTTP-only contract seam for full lifecycle independence, an unchanged API boot surface, and a clean auth boundary.

## Related

- ADR-0013 (`POST /api/ingest/{kind}` generic router) — the endpoint contract this server consumes.
- FR-1 (transport pin), FR-6 (fail-fast on missing `AGENTRISE_INGEST_TOKEN`) — `docs/features/ING-04/REQUIREMENTS.md`.
- R-06 (bearer-token handling), R-07 (no cross-service token leakage) — the security carry-forwards this topology preserves.
- DECISIONS.md D-01 (this ADR's source), D-07 (the config-drift companion — no `mcp_server:*` in `project-commands.yaml`, `# mcp-server` section in `stack-smoke.md`).
