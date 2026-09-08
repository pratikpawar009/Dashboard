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
