# ING-01 — Data Design

State & data management. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

```mermaid
erDiagram
    INGEST_TOKENS {
        string id PK "uuid4"
        string token_hash UK "sha256 hex, 64 chars"
        string label
        string user_email
        string_array allowed_program_ids "empty=allow-all; [\"*\"]=wildcard"
        datetime expires_at "nullable, defaults null"
        datetime revoked_at "nullable"
        datetime last_used_at "nullable, NOT written by this story"
    }
```

### `ingest_tokens` (postgres table — unchanged by this story)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `id` | `String` (uuid4) | PK | — | `services/api/app/models/ingestion.py:73` |
| `token_hash` | `String` | unique, not null | sensitive | SHA-256 hex digest of the raw token; never the raw value (:74) |
| `label` | `String` | not null | — | operator-supplied at mint |
| `user_email` | `String` | not null, `ix_ingest_tokens_user_email` | PII | owner-of-record, not a session identity this story reads |
| `allowed_program_ids` | `ARRAY(String)` | not null | — | `[]`=allow-all, `["*"]`=explicit wildcard, else membership list (ADR-0006 §3) |
| `expires_at` | `DateTime(tz)` | nullable | — | null at mint always (ADR-0006 §4); no CLI flag sets it in this story |
| `revoked_at` | `DateTime(tz)` | nullable | — | containment mechanism; no revoke path ships in this story (ING-03) |
| `last_used_at` | `DateTime(tz)` | nullable | — | **not written by this story** — no FR/TC requires it; a future token-inventory story (ADR-0006 § Flagged gaps) is the natural owner |

Table and all seven columns already exist (BED-01, `migrations/versions/001_initial_schema.py`). This story reads (auth-check) and inserts (mint) rows; it adds no column.

## 2. Migrations

N/A — no schema change. BED-01 already created `ingest_tokens`; ADR-0006 and `REQUIREMENTS.md` § Constraints both state this story ships zero migrations.

## 3. Ownership & tenancy

No per-request session identity exists on this auth path (bearer-token-only, no user context threading) — enforcement is scope-based, not row-ownership-based. `get_ingest_token()`'s `_check_program_scope` helper is the enforcement mechanism: given the resolved row's `allowed_program_ids` and the caller-supplied `program_id`, it fail-closes (403) except for ADR-0006's two accepted permissive defaults (empty array, `["*"]`). `user_email` records who minted a token for audit purposes only; it plays no role in the authorization decision. Minting authority itself is local-shell-plus-`DATABASE_URL`-credentials (ADR-0006 §2) — no RBAC-gated admin path exists to enforce anything against.

## 4. Data classification & retention

`user_email` is PII (BED-01's existing classification, unchanged). `token_hash` is sensitive: a one-way SHA-256 digest that cannot be reversed to the raw token, but is still the live lookup key for a real credential and must never appear in a log line (`ING-01-FR-5`). The raw token itself is never persisted anywhere — the `IngestToken` model docstring's SECURITY CRITICAL invariant (`ingestion.py:65-67`) — its only existence outside process memory is the single `stdout` line at mint. Retention: no TTL by default (`expires_at` null, ADR-0006 §4); revocation via `revoked_at` is the sole containment control. No deletion (soft or hard) logic ships in this story — a revoked row stays queryable indefinitely for audit.

## 5. Consistency & concurrency

Mint: one `INSERT` per invocation inside one transaction (`await session.commit()`, D-02) — always a new UUID-keyed row, never an update, so there is no write-write race to serialize. Auth check: a single-row `SELECT` by the unique `token_hash` index, read-only, no lock — two concurrent requests against the same live token each independently re-read the same row. No idempotency key is needed anywhere in this story's write path: mint is a manual, human-invoked, one-shot operation, never retried by automation.

## 6. Caching

N/A — no cache layer exists in this system (ADR-0002 § State & data: Postgres primary datastore only). Every `get_ingest_token()` call performs a fresh indexed lookup; the `< 10ms` p95 budget (`ING-01-NFR-performance`, `TC-22`) is met by the existing unique index on `token_hash`, not by caching the result.

## 7. Ephemeral / session state

N/A in the server/session sense — this auth path is stateless bearer-token verification, the same pattern AUTH-01's JWT path already establishes (`docs/requirements/auth.md` § session). The one genuinely ephemeral value in this story is the raw token itself, held only in the mint script's local process memory between generation and its single `print()` call — never persisted past that stdout line, never held in any server-side session store.

## 8. Query-path & access-path performance

One indexed point lookup per call: `SELECT ... FROM ingest_tokens WHERE token_hash = :hash` against the unique index SQLAlchemy's `unique=True` creates on that column, plus two in-SQL/Python datetime comparisons (`revoked_at`, `expires_at`) and an in-memory `allowed_program_ids` containment check (`ING-01-FR-3`) — no fan-out, no N+1, one row read per call. Budget: p95 `< 10ms` (`ING-01-NFR-performance`, `TC-22`, `tests/perf/test_ingest_token_auth_perf.py`). No pagination concern — this dependency reads exactly one row per invocation, never a list.

## 9. Contract (API / interface)

Registered cross-story contract — authored concretely in the shared registry, not duplicated here.

Contract: `ingest-token-auth` → `docs/requirements/auth.md#ingest-token-auth`

## 10. Async & messaging

N/A — purely synchronous request/response (auth check) and a one-shot CLI write (mint); no queue, topic, or background job.
