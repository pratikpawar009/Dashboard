# Architecture Decision Records

| ID | Title | Status |
|---|---|---|
| [ADR-0001](0001-tech-stack.md) | Tech stack | Accepted |
| [ADR-0002](0002-system-architecture.md) | System architecture | Accepted |
| [ADR-0003](0003-json-columns-jsonb.md) | JSON-typed schema columns use PostgreSQL JSONB | Accepted |
| [ADR-0004](0004-keycloak-oidc-authlib.md) | Keycloak OIDC via Authlib | Accepted |
| [ADR-0005](0005-programs-api-switcher-shape.md) | `programs-api` returns the switcher list shape | Accepted |
| [ADR-0006](0006-ingest-token-format-and-scope-semantics.md) | Ingest token format, scope semantics, and lifetime | Accepted |
| [ADR-0007](0007-program-detail-response-shape.md) | `program-detail-api` returns an ordered `summary` card array with server-owned glyph/label | Accepted |
| [ADR-0008](0008-client-side-auth-route-handler-proxy.md) | Client-side authenticated FastAPI calls go through a same-origin Route Handler proxy — FastAPI is never reached directly from the browser | Accepted |
| [ADR-0009](0009-personal-usage-api-response-shape.md) | `personal-usage-api` returns 5-field cards + a raw daily token series + a commands panel, server-owned presentation fields | Accepted |
| [ADR-0010](0010-program-roster-new-table.md) | `program_roster` is a new, additive table — file-authoritative program membership, kept separate from `program_members` | Accepted |
| [ADR-0011](0011-persona-precedence-new-table.md) | `persona_precedence` is a new, additive table — persona-precedence order rides AUTH-02's own 3-tier config mechanism, not `persona_config` | Accepted |
| [ADR-0012](0012-ingest-org-rollup-out-of-band.md) | `rebuild_org_rollups()` runs out-of-band from the ingest request path via FastAPI `BackgroundTasks` | Accepted |
| [ADR-0013](0013-generic-ingest-kind-router.md) | `POST /api/ingest/{kind}` is a single generic router; the old `POST /api/ingest/files` URL is retired | Accepted |
| [ADR-0014](0014-mcp-server-topology.md) | MCP server deployment topology — `services/mcp-server/` is a separately-deployed sibling service | Accepted |
| [ADR-0015](0015-program-id-sourcing-precedence.md) | Activity-hook `program_id` sourcing precedence — env → `.harness/program.yaml → program_id` (legacy `programId`) → skip | Accepted |
