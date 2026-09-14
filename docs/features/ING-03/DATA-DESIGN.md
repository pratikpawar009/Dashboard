# ING-03 — Data Design

State & data management for `POST /api/ingest/{kind}` with `kind="artifacts"`. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model

No new tables. The `program_artifacts` table shipped by BED-01 migration `001_initial_schema.py` is the write target; its schema is unchanged by this story.

### `program_artifacts` (postgres table) — consumed as-is (BED-01)

| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| `id` | `uuid` | PK | — | Row identity; unchanged by upsert on `(program_id, type)`. |
| `program_id` | `String` | FK → `programs.id` (BED-01), part of `uq_program_artifacts_program_id_type` | — | Envelope-tier scope (token-checked before this row is materialised). |
| `type` | `String` | part of `uq_program_artifacts_program_id_type` | — | One of the 5 canonical types — validated at the router/schema tier. |
| `count` | `Integer` | required | — | Non-negative artifact count for `(program_id, type)`. |
| `as_of_timestamp` | `DateTime(timezone=True)` | required | — | Producer-reported as-of; wire field `as_of`, stored as-is. |

Unique index `uq_program_artifacts_program_id_type` on `(program_id, type)` is what makes `ON CONFLICT DO UPDATE` idempotent (§ 5). No new indexes; no schema deltas.

The 5 canonical types come from PRD FR-ING-05 / `docs/prd/ai-sdlc-adoption-dashboards.md` § 8.4 and are pinned in the request schema (F-02) as `frozenset({"prd", "user_story", "test_case", "arch_diagram", "api_spec"})` — case-sensitive, no aliasing. Enforced at the request tier via a Pydantic v2 `field_validator` on `ArtifactCountsIn.counts` so the service never sees an invalid key (FR-2, D-03 domain risk).

## 2. Migrations

N/A — `program_artifacts` already exists (BED-01 migration `001_initial_schema.py`); no schema change, no data backfill, no new revision. `services/api/tests/test_migrations.py` is untouched.

## 3. Ownership & tenancy

Envelope-tier only. The router reads `program_id` off the raw JSON body once and calls `await get_ingest_token(program_id=..., credentials=..., session=db)` directly (not `Depends()`, per FR-5 / `app/api/manifest.py` precedent — the same shape ING-02 shipped). That resolves ING-01's 401 (`missing`/`unknown`/`revoked`/`expired`) and 403 (`scope`) branches verbatim. Every downstream call in this story receives the token-scope-checked `program_id` as an argument.

Unlike ING-02, there is no row-level scope check: the artifacts envelope is single-program-scoped by construction (`{program_id, kind, counts, as_of}` — one program, N types), so a row cannot smuggle a scope the token was not authorised for. No `program_id_mismatch` rejection reason exists for this route.

## 4. Data classification & retention

- `program_artifacts` rows are aggregate counts, non-PII by construction. `type` is a canonical string from a closed 5-entry enum; `count` is an integer; `as_of_timestamp` is a producer timestamp. None classify as PII/sensitive per PRD Data Classification.
- Retention: unchanged from BED-01 (no retention/purge/archival — accepted at BED-01 R-08). This story adds no retention logic.
- PII allowlist enforcement on the completion log (FR-5): the `ingest_artifacts_write` structured event carries exactly `{event, program_id, token_label, types_written}` — never `user_email`, `token_hash`, `as_of`, the raw `counts` values, or the request body. Asserted directly by F-15 (`test_ingest_artifacts_pii_logging.py`, T-09), mirroring ING-02's `_LOG_FIELD_ALLOWLIST` shape in `services/api/app/services/activity_ingest.py`.

## 5. Consistency & concurrency

- **Transaction boundary — request path**: one `AsyncSession` via `Depends(get_db)`. Router-tier validation (400 unknown kind → 401 missing/unknown token → 403 scope) and schema-tier validation (400 unknown canonical type) run BEFORE any write; a failure yields zero rows written, no partial commit. On success, the service performs a SINGLE `pg_insert(program_artifacts).values(rows).on_conflict_do_update(index_elements=["program_id", "type"], set_={"count": excluded.count, "as_of_timestamp": excluded.as_of_timestamp})` inside `session.begin()`, commits, and returns. No chunking (`≤5` rows fit in one INSERT — well below the 65_535 bind-parameter ceiling); no post-commit rebuild (D-03, § 10).
- **Idempotency**: `on_conflict_do_update(index_elements=["program_id", "type"])` on the existing `uq_program_artifacts_program_id_type` constraint. Same-payload re-POST yields the same row set with identical `count` and `as_of_timestamp`; `rows_upserted == len(counts)` in both calls; row count in `program_artifacts` for that `program_id` is unchanged (TC-01 assertion).
- **Partial-payload semantics (FR-4)**: only the types listed in `counts` are named in `values(rows)`; `ON CONFLICT DO UPDATE`'s `set_={}` clause touches only the columns Postgres receives in the excluded row. A type absent from the payload has NO row in `values(...)` and therefore NO conflict target — its existing row (if any) is neither read nor written. TC-01 seeds `user_story=7` beforehand, POSTs `{prd:3, test_case:12}` twice, and asserts the `user_story` row is unchanged both times.
- **Concurrent pushes on the same `(program_id, type)`**: two concurrent POSTs converge on the unique index — Postgres serialises via row-level locks acquired by `ON CONFLICT DO UPDATE`; last-writer-wins on `count` and `as_of_timestamp`. Acceptable: the producer is a single MCP tool (ING-04) invoked at commit-time; no real-world concurrent overwrite of the same `(program_id, type)` is expected. No advisory lock, no optimistic concurrency token — the row's `id` (uuid PK) is preserved on conflict (referential stability), only the count/timestamp columns are overwritten.
- **Bind-parameter ceiling**: N/A — a maximum of 5 rows × 4 non-key columns = 20 bind params per INSERT, orders of magnitude below Postgres's 65_535 limit. No named constant, no chunking.

## 6. Caching

N/A — no cache is introduced or consumed by this story. `program_artifacts` is the ledger for downstream governance-panel reads; a future read story may add caching, but the write path never reads back.

## 7. Ephemeral / session state

N/A — the request handler is fully stateless. No cookies, no server-held per-connection state, no URL-as-state. No BackgroundTask carries any state (§ 10 — no async dispatch at all).

## 8. Query-path & access-path performance

- **Reads (in-request)**: one `get_ingest_token` lookup (`ix_ingest_tokens_token_hash` unique index, ING-01 shipped). No pre-read to split inserted/updated — the response reports `rows_upserted` (not `inserted` vs `updated`) per D-02, so no `SELECT` is needed. This is a difference from ING-02, which pre-reads to populate `IngestFilesResponse.{inserted, updated}` distinctly.
- **Writes**: one `pg_insert(program_artifacts).on_conflict_do_update(...)` per request. At most 5 rows, one statement, one transaction. `uq_program_artifacts_program_id_type` supports the ON CONFLICT clause with O(log n) B-tree lookup per row.
- **Pagination**: N/A — bounded-size envelope (max 5 rows by construction of the canonical-type set); no list read exposed.
- **NFR budget (300 ms p95)**: split — bearer-token lookup ~10 ms + Pydantic validation ~5 ms + single-row upsert ~20 ms per row × ≤5 rows ~ 100 ms + JSON serialisation ~5 ms ≈ 120 ms median. Substantial residual margin against the 300 ms p95 budget on the measured evidence pattern from ING-02's tests (bearer + single-txn write). No accumulated-table-size cost curve (`program_artifacts` is at most 5 rows/program × O(programs), which is small; the ON CONFLICT lookup is O(log n) regardless).
- **Perf test (T-13, F-19)**: `services/api/tests/perf/test_ingest_artifacts_perf.py` marked `@pytest.mark.perf` per D-05. Seeds two OTHER programs' artifacts (proves program-scope isolation of the ON CONFLICT lookup), then measures the ≤5-row push against a third program; asserts p95 < 300 ms. No new runner install (marker already declared in `services/api/pyproject.toml`, ING-02 D-04); opt-in via `pytest -m perf`.

## 9. Contract (API / interface)

Registered cross-story contract. `ingest-artifacts-api` currently exists in `docs/requirements/api.md` with a stub shape (`produced_by: ING-03`, `consumed_by: [ING-04]`); this story fills in the concrete shape at that shared file, and this section is a bookmark:

`Contract: ingest-artifacts-api → docs/requirements/api.md#ingest-artifacts-api`

The full shape written by T-14 into the shared registry:

- **endpoint**: `POST /api/ingest/artifacts` (resolved as `POST /api/ingest/{kind}` with `kind="artifacts"` per ADR-0013 / D-01)
- **auth**: `ingest-token-auth` bearer (ING-01); envelope `program_id` must be in the token's `allowed_program_ids` or a `"*"` wildcard (or empty = allow-all — ING-01 semantics)
- **request_body**: `{program_id: str, kind: "artifacts", counts: {<canonical_type>: int, ...}, as_of: ISO-8601}` — envelope Pydantic bind on `ArtifactCountsIn`; `counts` keys validated against `frozenset({"prd", "user_story", "test_case", "arch_diagram", "api_spec"})`; unknown key → 400, zero writes
- **response_body**: `{rows_received: int, rows_upserted: int, rejections: list[RejectionEntry]}` (Q-02); `RejectionEntry` reused verbatim from `app/schemas/ingest_files.py` (index + reason only, never row content — FR-8 / C-7 discipline)
- **errors**: 400 (envelope invalid or non-canonical type key), 401 (missing/unknown/revoked/expired bearer — ING-01 branches), 403 (`allowed_program_ids` does not cover envelope `program_id`), 413 (`len(counts) > 5` — defence-in-depth, structurally impossible after the canonical-type check)
- **observability**: one structured log event `ingest_artifacts_write`, exact allowlist `{event, program_id, token_label, types_written}` (§ 4)

Also consumed (unchanged, frozen upstream):

- `Contract: ingest-token-auth → docs/requirements/auth.md#ingest-token-auth` — bearer resolution + 401/403 branches (ING-01, `app/core/ingest_auth.py`).
- `Contract: db-schema → docs/requirements/data.md#db-schema` — `program_artifacts` shape (BED-01, unchanged by this story).

Also updated in the same T-14 edit: `docs/requirements/api.md#ingest-files-api` gets a topology note pointing at ADR-0013 — the route path is now `POST /api/ingest/{kind}` with `kind="activity"` (URL `/api/ingest/activity`), not the retired `/api/ingest/files`. The `rows[]` field list, response shape, and error branches are unchanged.

## 10. Async & messaging

N/A — no async dispatch, no BackgroundTask, no queue, no cron.

ADR-0012's `BackgroundTasks` mechanism does NOT apply (D-03, PRD § Constraints). `program_artifacts` is a leaf counts table with no rollup source relationship — nothing under `services/api/app/services/rollup_rebuild.py` reads it, so no rebuild is warranted. The service function `ingest_artifacts(db, program_id, counts, as_of, token_label) -> IngestArtifactsResponse` has NO `on_org_rebuild` parameter and does NOT import `rebuild_program_rollups` or `rebuild_org_rollups`; F-16 (`test_ingest_artifacts_no_rollup_dispatch.py`, T-10) asserts the module-level import guard as a static-code check.

The generic router (F-04) still receives a `background_tasks: BackgroundTasks` parameter (unchanged from ING-02's dispatch signature — used for `kind="activity"`), but the `kind="artifacts"` dispatch branch never uses it. `background_tasks.add_task(...)` is not called in the artifacts path.
