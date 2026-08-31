# AUTH-03 — Data Design

State & data management for the RBAC check library. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

`N/A — AUTH-03 owns no persistent store.` The five checks read two upstream entities without persisting or transforming either: `CurrentUser` (AUTH-01's session contract — `user_id, email, role, groups, programs`, in-memory per request) and the persona string returned by AUTH-02's `PersonaResolver.resolve(role)` (backed by AUTH-02's own `persona_config` Postgres table and Tier-1/2 config, modeled in AUTH-02's own data design, not here). No new table, collection, or key namespace is introduced.

## 2. Migrations

`N/A — no schema change.` No Alembic revision is part of this story.

## 3. Ownership & tenancy

`N/A — no owned durable resource.` The only new mutable state this feature introduces is the process-lifetime `_persona_resolver` module reference (§7) — not tenant/user-scoped data, so no `user_id`/`program_id` ownership column or RLS policy applies.

## 4. Data classification & retention

The four structured log events this feature emits are the only data AUTH-03 produces. Field-level classification (AUTH-03-FR-2, D-02):

| Event | Fields | Classification | Notes |
|---|---|---|---|
| `rbac_check_org_access` | `user_id, persona, outcome, timestamp` | `user_id`: internal identifier, not PII by itself (no email/name). `persona`/`outcome`/`timestamp`: operational, not sensitive. | Both outcomes logged. |
| `rbac_check_governance_visibility` | `user_id, persona, outcome, timestamp` | same as above | Both outcomes logged (2026-08-31 decision, story Decision log). |
| `individual_view_denied` | `user_id, target_user_id, outcome, timestamp` | `target_user_id`: internal identifier only, same class as `user_id`. | Denials only. |
| `member_view_denied` | `user_id, program_id, target_member_id, outcome, timestamp` | `program_id`/`target_member_id`: internal identifiers only. | Denials only. |

No event ever carries `email`, `groups`, JWT claims, session id, or request path — enforced structurally by the exact-allowlist logging helper (T-01) and asserted per-event by a PII-audit test (AUTH-03-TC-20..23, pattern: AUTH-02's `test_persona_mapping_loaded_event_contains_no_pii_tc15`). Retention/encryption-at-rest for the JSON log stream itself is owned by the log-aggregation infrastructure this app writes stdout to (unspecified, out of scope for AUTH-03 — no new retention policy is introduced here).

## 5. Consistency & concurrency

`N/A — no concurrent-write hazard.` Every check is a stateless, side-effect-free (besides logging) pure function; there is no shared mutable data structure among concurrent requests. The one process-lifetime write (`rbac.configure()`, §7) happens exactly once, synchronously, during `create_app()`, strictly before any request is served — no lock is needed (contrast with AUTH-02's `PersonaResolver._cache`, which is genuinely concurrently written per-request and asyncio.Lock-guarded; that concern belongs to AUTH-02, not here).

## 6. Caching

`N/A — AUTH-03 owns no cache.` Each persona-resolving check calls AUTH-02's `PersonaResolver.resolve(role)`, which owns its own per-role 300s TTL cache (`app/core/persona_resolver.py`). AUTH-03 relies on that cache as-is (D-05) — a warm hit is <1ms (AUTH-02-TC-12); request-scoped memoization across multiple checks in one request is explicitly deferred (`REQUIREMENTS.md` § Scope, Out).

## 7. Ephemeral / session state

Two distinct lifetimes:

- **Per-request, not persisted**: `current_user: CurrentUser` and the check's own arguments (`program_id`, `target_user_id`, `target_member_id`) — supplied by the caller (a downstream route handler), read once per check call, never written back anywhere.
- **Process-lifetime, set once**: `app.core.rbac._persona_resolver` (D-06) — a module-level reference to the app's `PersonaResolver` instance, written exactly once by `create_app()` via `rbac.configure(app.state.persona_resolver)` (F-05), read on every persona-resolving check call for the life of the process. This is deliberately narrower than `app.state.*`'s per-app-instance scoping (D-07) — AUTH-03's own unit tests never build a FastAPI app, so they set this reference directly (`rbac.configure(stub_resolver)`) rather than through `request.app.state`.

## 8. Query-path & access-path performance

No query path — every check is in-process, O(1), zero I/O (`REQUIREMENTS.md` § Constraints). Budget: `< 5ms p95` per check, in-process (story Decision log, 2026-08-26 assumption; NFR-performance, AUTH-03-TC-26). The dominant cost per persona-resolving check is AUTH-02's `resolve()` call — a warm cache hit (<1ms, AUTH-02-TC-12) in the common case; a cold Tier-3 miss is bounded by AUTH-02's 3.0s hard timeout but is out of AUTH-03's own 5ms budget by design (a cold resolve is amortized once per role per 300s across the whole process, not per RBAC check).

## 9. Contract (API / interface)

Contract: `rbac-checks` → `docs/requirements/auth.md#rbac-checks`. Produced by this story, consumed by AUTH-04, OVW-01..04, PGD-01..06, SHP-02..06 (16 stories). The concrete shape (five async function signatures, error/exception behavior, cascade order, logging field allowlists) is authored there, not duplicated here.

## 10. Async & messaging

`N/A — purely synchronous.` No queue, topic, or scheduled job is introduced. Every check is an `async def` for call-shape consistency with the rest of the auth stack (`AUTH-01`/`AUTH-02`'s own async dependency chain), not because it awaits any I/O of its own.
