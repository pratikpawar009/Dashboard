# ADR-0013: `POST /api/ingest/{kind}` is a single generic router; the old `POST /api/ingest/files` URL is retired

- Status: Accepted
- Date: 2026-09-13
- Deciders: Pratik Pawar (PO+Architect, single-approver mode)

## Context

ING-02 (`phase: review`, PR #296 not yet merged) shipped `POST /api/ingest/files` for `kind="activity"` batches. ING-03 needs `POST /api/ingest/artifacts` for the artifact-counts envelope. Two obvious topologies exist: (a) two independent handlers (`/files` for activity + `/artifacts` for artifacts) on the shared `/api/ingest` router, or (b) one generic handler `POST /api/ingest/{kind}` that resolves the service by the `kind` path-param and re-uses the envelope-`kind` allowlist ING-02 D-03 introduced in `services/api/app/core/ingest_kind.py`.

Two constraints settle it. First, ING-02 D-03 already codifies the "envelope-kind vocabulary lives in one module" discipline precisely because four `kind` vocabularies (envelope, row-level, manifest, files-strategy) were drifting apart; a two-handler topology re-introduces the same drift (each handler duplicates the router-tier accept check on its own subset). Second, the story's AC-1 wording `POST /api/ingest/artifacts` is fully satisfied by the generic route — `kind="artifacts"` resolves to that exact URL. The trade-off is that under (b) `kind="activity"` resolves to `/api/ingest/activity`, retiring ING-02's shipped `/files` URL.

ING-02 is not merged (PR #296 at `phase: review`); no external caller has bound against `/api/ingest/files`. Retiring it now is a coordinated same-cycle refactor of a pre-shipped route, not a customer-visible breaking change. Downstream `ingest-files-api` consumers (`ING-04`, `ING-06`, `ING-09` per `docs/requirements/api.md#ingest-files-api`) all bind after this URL change lands; they inherit the new topology as their starting assumption.

## Decision

`POST /api/ingest/{kind}` is the single handler on the shared `/api/ingest` router (module renamed `services/api/app/api/ingest_files.py` → `services/api/app/api/ingest.py`). `kind` is a path-parameter validated against `services/api/app/core/ingest_kind.py::_ACCEPTED_KINDS` at the router tier, BEFORE bearer-auth (per `docs/requirements/api.md` ordering, "Router-tier check, before auth"). This ADR extends `_ACCEPTED_KINDS` from `frozenset({"activity"})` to `frozenset({"activity", "artifacts"})` in the same PR. After the kind accept-check + auth + body validation, the handler dispatches by kind: `"activity"` → `app.services.activity_ingest.ingest_files(...)` (unchanged, ING-02); `"artifacts"` → `app.services.ingest_artifacts.ingest_artifacts(...)` (new, ING-03).

`kind="activity"` semantics are preserved BYTE-FOR-BYTE from ING-02: same request body (`{program_id, kind:"activity", rows[≤5000]}`), same `IngestFilesResponse` shape, same status-code ordering (400 envelope invalid → 401 missing/unknown token → 403 scope → 413 rows-cap), same PII allowlist on `ingest_write_completed`, same out-of-band org-rollup dispatch via `BackgroundTasks` (ADR-0012). Only the URL changes: `/api/ingest/files` → `/api/ingest/activity`. ING-02's four route-touching test files (`test_ingest_files_idempotency.py`, `test_ingest_files_auth_denial.py`, `test_ingest_files_route_registered.py`, `test_ingest_files_perf.py`) get URL-constant edits only; assertions on body, response, status-code ordering, and PII allowlist stay unchanged.

The old `POST /api/ingest/files` URL is retired without a compatibility alias. `kind="files"` is NOT an accepted kind — it does not resolve to the activity handler under the new topology, and no legacy `/files` route stays registered. `docs/requirements/api.md#ingest-files-api` is amended to document the new route path; the contract's field-list stays the frozen wire contract ING-02 T-16 authored.

## Consequences

**Positive**

- One authoritative accept-check for envelope-kind at the router tier; no drift between per-kind handlers. Follows the ING-02 D-03 rationale to its endpoint.
- Adding a future `kind` (e.g. `"manifest-events"`) requires exactly two edits: append to `_ACCEPTED_KINDS`, register a service in the dispatch. No new route module.
- The AC-1-mandated URL `POST /api/ingest/artifacts` is served by the generic route without special-casing.
- ING-02's shipped semantics (validation ordering, response envelope, PII discipline, ADR-0012 background dispatch) are preserved with a URL-only edit on four test files — the substance of TC-01/TC-02 (`#293`, `#294`) is unchanged.

**Negative**

- URL breaking change on ING-02's `/api/ingest/files`. Accepted because ING-02 is pre-merge (PR #296, `phase: review`) — no external caller exists.
- The `services/api/app/api/ingest_files.py` filename is renamed to `ingest.py` to match the new generic semantics. This is a `git mv` with import-path updates in `services/api/app/main.py`; historical grep for `ingest_files.py` no longer hits the router module. Mitigated by `git mv` preserving history and by the module docstring pinning the rename rationale.
- Downstream ADR-0012 (`rebuild_org_rollups()` background dispatch) applies to `kind="activity"` only. The generic dispatcher must NOT wire an `on_org_rebuild` callable into the `kind="artifacts"` path — ADR-0012 is `kind="activity"`-scoped. Enforced structurally: `ingest_artifacts.ingest_artifacts()`'s signature has no `on_org_rebuild` parameter, and a unit test (`test_ingest_artifacts_no_rollup_dispatch.py`) asserts the service module does not import `rebuild_program_rollups` or `rebuild_org_rollups`.

**Reversible?**

Yes — mechanical. Reverting is a `git mv services/api/app/api/ingest.py services/api/app/api/ingest_files.py`, restoring the `/files` route (or keeping `/api/ingest/{kind}` and adding an alias route `@router.post("/files")` that forwards to the activity dispatch), and reverting the URL constants in the four ING-02 test files. Because ING-03's artifact service is invoked only from the `kind="artifacts"` dispatch, unwinding the generic router does not touch the artifact service code path. No data migrated under this choice; no persistent state depends on the URL.
