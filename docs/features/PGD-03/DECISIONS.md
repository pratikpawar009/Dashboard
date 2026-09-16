# PGD-03 — Decisions

Decision log for the Releases list (paginated) story. Header slugs (`blast:`/`rev:`) are the
greppable half of the record; `plan-validation`'s Decision-promotion dimension reads them.

### D-01: `limit` default is declared at the route, not by changing `get_offset_limit`'s default · blast:feature · rev:mechanical · adr:—

**Context**: FR-PGD03-5 requires an omitted `limit` to resolve to `20` for this endpoint, but
`app/dependencies/pagination.py::get_offset_limit` (BED-02 D-01) hardcodes `Query(MAX_OFFSET_LIMIT, ge=1)`
— its `limit` default is `50`. Changing that default would silently change the default for every
other current or future caller of the shared dependency, and no other caller has asked for 20.

**Decision**: Do not fork or edit `get_offset_limit`. Declare a story-local wrapper,
`_releases_offset_limit(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1)) -> tuple[int, int]`,
in `app/api/overview.py`, which applies the exact same `min(limit, MAX_OFFSET_LIMIT)` clamp
imported from `app/dependencies/pagination.py` (re-using `MAX_OFFSET_LIMIT`, not a second literal
`50`). The shared dependency is untouched; only PGD-03's own default changes.

### D-02: Response wire contract emits mockup field names directly, with `tagColor`/`tagBg` hoisted to the top level · blast:feature · rev:mechanical · adr:—

**Context**: The mockup's row shape (`ver`, `label`, `dot`, `tagColor`, `tagBg`, `date`, `stories`,
`prs`) diverges from `program_releases`' column names (`version`, `type`, `date`, `story_count`,
`pr_count`), and `tagColor`/`tagBg` are program-level (identical every row) rather than
per-release. PGD-01/PGD-02 precedent is that the API emits the mockup's shape verbatim
(pre-formatted, no client-side remapping).

**Decision**: `ProgramReleaseItem` ships exactly `{ver, label, dot, date, stories, prs}` (no
per-row `tagColor`/`tagBg`); `ProgramReleasesResponse` hoists `tag_color`/`tag_bg` (wire:
`tagColor`/`tagBg`) to the top level alongside `items`/`relTotal`. `stories`/`prs` are emitted as
strings (`str(story_count)`/`str(pr_count)`), `date` as `"Jul 15"` (month abbreviation + day, no
year, via Python's `%b %-d` equivalent handled portably with `strftime("%b ") + str(day)` to avoid
platform-specific `%-d`/`%#d` flags). This mirrors the `dot_style_for_program`/`bar_style_for_share`
precedent in `app/utils/format.py` of the producer emitting ready-to-bind presentation values.

### D-03: Status-indicator vocabulary is a fixed 3-entry map, out-of-vocabulary `type` raises · blast:feature · rev:mechanical · adr:—

**Context**: FR-PGD03-3 supersedes the story's `major|minor|patch` Decision-log assumption with
the mockup's actual 3-entry vocabulary. A `program_releases.type` value outside that set has no
rendering rule, and the mockup never demonstrates a 4th/unstyled row.

**Decision**: A module-level `dict[str, tuple[str, str]]` in `app/services/program_releases.py` maps
`type` → `(label, dot_hex)` for exactly `{"Feature release": ("Feature release", "#1f8a5b"),
"Patch release": ("Patch release", "#2a6fdb"), "Hotfix": ("Hotfix", "#d1495b")}`. A `type` not in
this map raises `ValueError` inside the service, which the route lets propagate to FastAPI's
catch-all 500 handler (`app/core/errors.py`) — never a silently unstyled row. Logged at `error`
level with the offending `program_id`/`release_id`, never the raw unmapped `type` value verbatim
beyond what's needed to diagnose (values here are internal seed/rollup data, not user input, so no
truncation/PII concern applies).

### D-04: Migration 007 adds `(program_id, date)` compound index; `ProgramReleases.__table_args__` updated to match · blast:data · rev:medium · adr:ADR-0015

**Context**: FR-PGD03-7 requires confirming index coverage for the mandatory `WHERE program_id = :pid
AND date >= :range_start ORDER BY date` query shape before claiming the NFR-002 ≤2s budget. Research
confirmed (§ Database) that the only existing index is `ix_program_releases_program_id` — no
compound `(program_id, date)` index exists. `alembic-patterns` requires migration + ORM
`__table_args__` + `test_migrations.py`/`test_models.py` schema-diff-gate fixture to change
together (004_rollup_query_indexes.py precedent; BED-05 AF-09 shows the failure mode when only the
migration changes). Per the `decide` skill's promotion rule, `blast:data` alone (regardless of
`rev:`) requires promotion to a full ADR — a durable schema change reaches beyond this one story.

**Decision**: New migration `007_program_releases_date_index.py` (down_revision
`006_usage_events_source_credits`) adds `op.create_index("ix_program_releases_program_id_date",
"program_releases", ["program_id", "date"])`, plain (not `postgresql_concurrently`, matching
002/004 precedent — no deploy runbook/CI requires a maintenance window today). `ProgramReleases.__table_args__`
in `app/models/rollup.py` gains this second `Index(...)` entry alongside the existing
`ix_program_releases_program_id` (kept — the single-column index still serves the count-without-date
case, though none exists today; removing it is out of scope and not requested by any FR). The
`tests/fixtures/prd_8_4_schema.json` fixture consumed by `test_models.py::TestFixtureDrivenTableConstraints`
is updated in the same task to list both indexes, per the alembic-patterns gate discipline. Promoted
to `docs/adr/0015-program-releases-date-index.md` (`adr-template`); `docs/adr/README.md` index updated.

### D-05: Frontend consumes the endpoint through the existing AUTH-05 proxy pattern, not a direct FastAPI call · blast:feature · rev:mechanical · adr:—

**Context**: ADR-0008 (client-side-auth-route-handler-proxy) established that the browser never
calls FastAPI directly; `programDetailApi.ts` (server) + `/api/proxy/program-detail/[program_id]/*`
(Route Handler) + `programDetailApi.client.ts` (client fetch) is the shipped 3-layer split for both
PGD-01 and PGD-02. No FR in this story asks for a different pattern.

**Decision**: PGD-03 adds a fourth sibling following the identical 3-layer split:
`fetchProgramReleases` in `programDetailApi.ts` (server, attaches bearer token, targets
`GET {API_BASE}/api/overview/program-detail/{id}/releases?range=&offset=&limit=`), a new proxy
route at `apps/web/src/app/api/proxy/program-detail/[program_id]/releases/route.ts` (mirrors the
token-trend proxy's `callWithAuth` retry-once + status mapping verbatim), and
`fetchProgramReleases` in `programDetailApi.client.ts` (client, same-origin proxy call, `range` +
`offset`/`limit` query params). No new proxy pattern, no new auth seam.

### D-06: Empty data source is accepted as a known-risk read path, not blocked or worked around · blast:feature · rev:mechanical · adr:—

**Context**: `rollup_rebuild.py` deletes all `program_releases` rows per rebuild and inserts none
(BED-03 D-03, deliberate — no release signal exists in `usage_events`). No release-ingestion story
exists in the RTM. The user explicitly directed (2026-09-16) that PGD-03 build the read path
anyway rather than widen scope to build a producer.

**Decision**: Ship the endpoint, panel, and tests exactly as specified. Do not modify
`rollup_rebuild.py`. Test fixtures seed `program_releases` directly (bypassing the
non-existent ingest path). Carried forward in PLAN.md § 6 as a HIGH risk and as an explicit
recommendation to intake a release-ingestion story — not built here.
