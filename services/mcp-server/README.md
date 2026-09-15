# agentrise-mcp

Local MCP server exposing `push_activity` and `push_artifacts` against the AgentRise ingest API.

Sibling service to `services/api/` — separately deployed, NOT wired into the main API's preflight
(see [ADR-0014](../../docs/adr/0014-mcp-server-topology.md) and ING-04 D-01 / D-07).

## Requirements

- Python 3.11

## Install

Use a fresh virtual environment — do NOT reuse `services/api/.venv` (D-01 isolation).

```bash
cd services/mcp-server
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Environment variables

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `AGENTRISE_INGEST_TOKEN` | yes | — | Bearer token for the ingest API. Missing / empty triggers fail-fast per FR-6 / D-06 before any HTTP or filesystem call. |
| `AGENTRISE_INGEST_BASE_URL` | no | `http://127.0.0.1:8000` | Base URL of the AgentRise ingest API. |

## Run

```bash
agentrise-mcp
# or
python -m agentrise_mcp
```

Boots FastMCP with streamable HTTP transport on `0.0.0.0:3010` path `/mcp` (FR-1, D-02).

## Tools

- `push_activity(program_id?, workspace_root?)` — reads `.harness/program.yaml` `files[]` and POSTs
  activity rows to `POST /api/ingest/activity` (FR-2, D-03).
- `push_artifacts(program_id?, workspace_root?)` — reads `.harness/program.yaml` `artifacts{}` and
  POSTs governance counts to `POST /api/ingest/artifacts` (FR-3, D-03).

See `docs/features/ING-04/REQUIREMENTS.md` for the full contract.

## Testing

```bash
pytest -q
```

## Deployment

Standalone service — its own CI + deploy pipeline. NOT invoked from
`docs/config/project-commands.yaml::preflight` (D-01 / D-07). Smoke procedure lives in
`docs/config/stack-smoke.md` under the `# mcp-server` section.
