# BED-03 — Decisions

Non-trivial technical choices made while planning BED-03's rollup rebuild engine. Header slugs (`blast:`/`rev:`/`adr:`) are machine-greppable per the `decide` skill.

### D-01: Transaction scope is per-call, not a single cross-scope transaction · blast:service · rev:mechanical · adr:—

**Context**: Research risk #1 (CRITICAL) described "all 13 rollup table mutations... must commit or roll back together" as if program-scope and org-scope rebuilds shared one atomic unit. Ground truth corrects the table count to 10 (7 program + 3 org, not 13), and FR-2 states each rebuild *call* — not each rebuild *story* — wraps its own affected tables in one `async with session.begin():` block. Nothing in AC-1/AC-2/AC-4 requires a program-scope call and an org-scope call to commit or roll back together; they are invoked independently (by ING-02/ING-06, out of this story's scope) and tested independently.

**Decision**: `rebuild_program_rollups(session, program_id)` wraps its 7 program-scoped tables' DELETE+INSERT in one transaction; `rebuild_org_rollups(session)` wraps its 3 org-scoped tables' DELETE+INSERT in a separate transaction. The two scopes are never combined into a single cross-scope transaction. A failure inside one scope's transaction rolls back only that scope's tables (TC-10); the other scope's most recent successful rebuild remains visible.

### D-02: Session-factory wiring point is `app/main.py` module-level import + shutdown disposal · blast:service · rev:mechanical · adr:—

**Context**: Research condition C-1 requires `app/core/db.py`'s session factory to be "wired at app startup (module-level engine, not per-request construction)" — but `app/main.py` has no lifespan/startup-event framework today (no `@app.on_event`/`lifespan=` exists; `configure_logging()` is the only import-time side effect it currently has).

**Decision**: `app/core/db.py` constructs `engine = create_async_engine(settings.database_url)` and `SessionLocal = async_sessionmaker(...)` at module import time (Python's own import-caching guarantees a process-wide singleton). `app/main.py` imports `engine` from `app.core.db` at module level — alongside the existing `configure_logging()` import-time pattern — so the engine is constructed deterministically when the app boots, not lazily whenever some future route first calls `get_db()`. `app/main.py` also registers `@app.on_event("shutdown")` to `await engine.dispose()`, avoiding leaked pooled connections, without introducing a full `lifespan=` context refactor this story does not otherwise need.

### D-03: Non-derivable descriptive/config fields default deterministically; `program_releases` writes zero rows until a release-signal exists · blast:feature · rev:mechanical · adr:—

**Context**: Several rollup fields have no analog in `usage_events`: `program_summary.name/icon/type/description/repos_with_harness_installed/repos_total/user_stories_delivered`, `program_releases.version/type/date/story_count/pr_count`, `program_members.name/role`, `user_sessions.name`. AC-1/AC-2 require every value "derived solely from `usage_events`," and this story's scope explicitly excludes joining against other data sources (a config/registry story is out of scope, per REQUIREMENTS.md § Scope). `usage_events` (`app/models/ingestion.py`) carries no release/version/story-count/PR-count column at all — there is no candidate signal for `program_releases`, not even an indirect one.

**Decision**: fields with no `usage_events` analog default deterministically on every rebuild — string fields to `""`, numeric fields to `0` — so full-replace stays idempotent (same input → same defaulted output, not a random or carried-over value). `program_members.name`/`user_sessions.name` fall back to the `usage_events.user` identifier, the only identity signal present. `program_releases` specifically has zero derivable columns: `rebuild_program_rollups` deletes any existing `program_releases` rows for the program and inserts none (an honest "no releases derivable from event data," not a fabricated row). Each field mapping is documented inline in `rollup_rebuild.py` per FR-3. Carried forward as risk R-09 in PLAN.md §6 — a future release-ingestion story must either add a release signal to `usage_events` or source `program_releases` from a different table, at which point this default is revisited.

### D-04: Idempotency comparison excludes `id`, `as_of_timestamp`, `created_at`, `updated_at` · blast:feature · rev:mechanical · adr:—

**Context**: Every rollup table's `id` primary key is regenerated on each INSERT (full-replace deletes then re-inserts fresh rows via the model's `default=lambda: str(uuid.uuid4())`), and staleness-marker columns (`as_of_timestamp`, plus `org_summary_rollup.created_at`/`updated_at`) are set to "now" on every rebuild call by design. AC-3's idempotency requirement ("byte-identical rollup rows") and TC-05/TC-06's "checksum + `COUNT(*)`" mechanic would always fail under a naive full-row checksum, since `id` and the timestamp columns differ between any two calls even when the underlying `usage_events` set is byte-identical.

**Decision**: "idempotent" means the *business-value* columns are identical across two rebuild calls over an unchanged `usage_events` set — not the full row. TC-05/TC-06's checksum is computed over each table's column set minus `{id, as_of_timestamp, created_at, updated_at}`. `id` values are not required to be deterministic across rebuilds; the existing `uuid4()` model default is left unchanged. This is stated explicitly so the idempotency tests (T-07) don't get built against a full-row hash that can never pass.

### D-05: Single-pass aggregation computed in Python after one raw `SELECT`, not via SQL CTEs/window functions · blast:service · rev:mechanical · adr:—

**Context**: FR-3 names CTEs/window functions as an example single-pass mechanism, and research's Top Recommendation 2 suggested the same. But the perf ceiling (C-4) is 5,000 `usage_events` rows per program — small enough to hold entirely in process memory — and hand-written multi-CTE SQL producing 7 differently-shaped aggregates (scalar sums/counts, per-user grouping, per-date series) is harder to unit-test, review, and keep O(events for the program) than the equivalent Python.

**Decision**: `rebuild_program_rollups` issues exactly one `SELECT * FROM usage_events WHERE program_id = :pid` via the ORM (verified by TC-11's `before_cursor_execute` listener asserting a SELECT count of 1 against `usage_events`); `rebuild_org_rollups` issues exactly one unfiltered equivalent grouped by `program_id` (TC-12). Both materialize the result set once and compute every table's aggregate values in Python from that single in-memory list — satisfying FR-3's "one filtered read, not N scans" without hand-written multi-CTE SQL. Each table's aggregation logic is a plain Python reduction, documented inline per FR-3's docstring requirement.

### D-06: `RebuildResult` is a frozen `dataclass`, not a `NamedTuple` · blast:feature · rev:mechanical · adr:—

**Context**: FR-1 leaves the shape open ("a small `dataclass`/`NamedTuple`"). This codebase already has one precedent (`tests/conftest.py`'s `@dataclass class AlembicRunner`) and no `NamedTuple` usage anywhere.

**Decision**: `RebuildResult` is `@dataclass(frozen=True)` with fields `scope: Literal["program", "org"]`, `program_id: str | None`, `duration_ms: int`, `event_count: int` — matching the existing dataclass precedent and giving callers immutability without a second construction API (`NamedTuple`'s tuple-unpacking) this codebase doesn't otherwise use.
