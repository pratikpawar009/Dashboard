# ADR-0011: `persona_precedence` is a new, additive table — persona-precedence order rides AUTH-02's own 3-tier config mechanism, not `persona_config`

- Status: Accepted
- Date: 2026-09-10
- Deciders: Pratik Pawar (Product Owner), AUTH-07 planning (via impl-planning-agent, `/arh-plan-implementation AUTH-07`)

## Context

AUTH-02's persona-resolver ships a 3-tier config mechanism (Tier-1 `PERSONA_ROLE_MAP` env JSON, Tier-2
`persona_role_map.yaml`, Tier-3 Postgres `persona_config`) for exactly one question: which persona does
a given `role` map to. AUTH-07 needs a second, independent piece of ops-configurable data — an ORDERED
persona precedence list, used to pick a single deterministic winner when a token carries several
mappable roles (live regression 2026-09-10: `realm_access.roles = ['Architect', 'Developer', 'developer']`
must always resolve to `architect`, never order-dependent). `persona_config`'s schema (`role` primary
key, `persona` column) has no way to represent an ORDER, and repurposing it — e.g. adding a `rank` column
that is only meaningful for a handful of canonical persona rows and meaningless for every other
role→persona row — would conflate two different concepts (a role's own mapping vs. a global ranking
of personas) in one table.

## Decision

Add `persona_precedence` as a new, additive Postgres table (`rank int primary key, persona str not null`)
via its own Alembic revision (`005_persona_precedence.py`), following ADR-0010's precedent of a small,
purpose-built table rather than overloading an existing one. Precedence is sourced through the SAME
3-tier mechanism already established for role mapping, not a new one: Tier-1 `PERSONA_PRECEDENCE_ORDER`
env JSON array (parsed once at `Settings` load, fail-open on parse error — mirrors `PERSONA_ROLE_MAP`);
Tier-2 a new root-level `precedence:` key in the existing `services/api/config/persona_role_map.yaml`
(loaded once at `PersonaResolver.__init__`; a malformed value is a startup failure, matching the existing
malformed-YAML fail-fast behavior); Tier-3 this new table, queried `ORDER BY rank` through the resolver's
existing injectable `session_factory` and 3.0s `asyncio.wait_for` timeout, and cached in-process for 300s
using the resolver's existing TTL/lock pattern (a dedicated cache entry, never colliding with a real role
name) so a steady-state deployment issues at most one Tier-3 precedence query per 300s per worker, not
one per request. All three tiers unset falls back to the hardcoded default
`["cio", "architect", "product-manager", "engineering-manager", "developer"]` — no working deployment
must configure anything to get today's intended order.

## Consequences

- Positive: an operator can re-order persona precedence (e.g., to prefer `architect` over `cio` for a
  dual-role account) via an env var, a YAML edit, or a table update, with no code change — mirrors
  AUTH-02's own "no hot-reload, but ops-tunable within a bounded TTL" tradeoff, rather than inventing a
  new config paradigm for this one value.
- Negative: a second small ops-configuration table now exists alongside `persona_config`, with no
  foreign-key or other structural link between them (both are read independently by the resolver).
  Precedence is a single global, org-wide ranking — not scoped to `program_id` or any tenant — so a
  future per-tenant precedence requirement would need a new column, not supported today.
- Reversible? Medium. The table can be dropped and precedence falls back to the hardcoded default order
  with zero data loss — this is pure ranking CONFIGURATION, not durable business/audit data, unlike
  `program_roster` (ADR-0010). The migration itself (once shipped to a live deployment) still needs a
  reviewed follow-up revision to remove, so "medium" not "mechanical" — but there is no data-loss risk
  driving that number up to "effectively irreversible."
