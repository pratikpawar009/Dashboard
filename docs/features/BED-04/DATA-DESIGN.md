# BED-04 — Data Design

State & data management for the ingestion-freshness accessor. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

No new table/column. `freshness.py` reads BED-01's existing `system_metadata` singleton table **read-only**, via its own `session_factory` (default `app.core.db.SessionLocal`) — it issues the query itself (unlike BED-02's compute functions, which take pre-fetched rows). Full table shape lives in `docs/features/BED-01/DATA-DESIGN.md`; only the fields this story reads are named below.

### `system_metadata` (postgres table, read-only from this story)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `key` | String | PK | — | queried with `WHERE key = 'ingestion'` |
| `last_successful_run_at` | DateTime(timezone=True) | NOT NULL | — | returned to callers as-is; no formatting/transformation |

## 2. Migrations

N/A — no schema change. `services/api/migrations/versions/` is untouched; the table already exists via BED-01's `001_initial_schema.py`.

## 3. Ownership & tenancy

N/A — `system_metadata` is a process-wide singleton row (`key='ingestion'`), not scoped to a user, tenant, or program. No caller-supplied resource id is accepted, so no `_load_owned`-style ownership check applies (`.claude/rules/security-baseline.md`'s ownership section governs per-resource mutations; this accessor takes no id and performs no mutation).

## 4. Data classification & retention

N/A — no PII/sensitive field. `key` and `last_successful_run_at` are operational metadata; the accessor logs neither a user identifier nor request content on any path (REQUIREMENTS.md § Non-functional requirements, Security). No retention/deletion policy change.

## 5. Consistency & concurrency

Single indexed primary-key read (`SELECT ... WHERE key = 'ingestion' LIMIT 1`), no write from this accessor. Concurrent callers on one `FreshnessAccessor` instance are serialized through an `asyncio.Lock` double-check (D-01, mirroring `PersonaResolver`) so a burst of concurrent cold calls issues at most one database read, not one per caller — **on the success path**. Since D-04, a timed-out caller releases the lock and the next re-checks an empty cache, so under a sustained stall N queued callers issue N reads and the Nth waits N x 3.0s (measured: 3.015s / 6.035s / 9.055s for three callers against a locked table). Every caller stays bounded, which is what F-1 required; flattening the queue to 3.0s for all callers would need in-flight-future sharing and is a decision for the consuming stories, which are the first to share one instance across concurrent requests (carry-forward CF-BED-04-03). No idempotency key needed — the operation is a pure read with no side effect beyond the in-process cache write.

## 6. Caching

- **Key**: none needed beyond the instance itself — `system_metadata` has exactly one row this story reads (`key='ingestion'`), so the cache holds a single `(value, expiry)` pair per `FreshnessAccessor` instance, not a dict keyed by role/id (contrast `PersonaResolver`, which caches per-role).
- **TTL**: 300s (D-02), tracked via `time.monotonic()`.
- **Invalidating event**: TTL expiry only. The writer (the out-of-process ingester) cannot invalidate an in-process cache, so TTL length *is* the worst-case apparent staleness (REQUIREMENTS.md § Constraints) — `no TTL — sync-invalidated` does not apply here; this is the `TTL-only` case the skeleton's caching section anticipates.
- A row-absent outcome is never cached (D-03) — every call re-queries while absent.

## 7. Ephemeral / session state

N/A — no client/session state. The only non-durable state is the in-process cache already described in § 6; there is no separate ephemeral surface (no cookie, no URL param, no per-connection server state).

## 8. Query-path & access-path performance

- One indexed primary-key `SELECT` per cache miss, bounded to at most once per 300s per `FreshnessAccessor` instance regardless of call volume (satisfies `.claude/rules/performance-baseline.md`'s no-unbounded-fan-out bar).
- Warm-hit path is O(1): an attribute comparison against `time.monotonic()`, no I/O — budget < 10ms p95 (BED-04-NFR-performance, proven by BED-04-TC-03).
- The cache-miss read is bounded by an explicit 3.0s `asyncio.wait_for` timeout (D-04, DECISIONS.md), matching `persona_resolver`'s Tier-3 bound — a stalled connection raises `HTTPException(500)` rather than blocking every caller sharing the accessor's lock indefinitely.
- No pagination applies — this is a singleton-row accessor, not a list endpoint.

## 9. Contract (API / interface)

Registered cross-story contract — concrete shape authored once at the shared registry, this section is a bookmark only:

`Contract: freshness-api → docs/requirements/api.md#freshness-api`

## 10. Async & messaging

N/A — the accessor is a synchronous-per-call async function with no message, event, or job produced or consumed. It has no writer counterpart in this story (REQUIREMENTS.md § Scope: the ingestion writer is out of scope, ING-02+).
