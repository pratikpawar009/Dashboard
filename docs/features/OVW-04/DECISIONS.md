# OVW-04 — Decisions

Decision log for the Program board story. Header carries `blast:`/`rev:`/`adr:` slugs for greppable audit.

### D-01: Add `ix_program_summary_tokens` index for `ORDER BY tokens DESC` (research C-1) · blast:data · rev:mechanical · adr:ADR-0017

**Context**: `program_summary` (`001_initial_schema.py`) has only a unique constraint on `program_id` — no index exists on `tokens`. FR-2 requires `ORDER BY tokens DESC`, and research condition C-1 makes index verification a pre-code, merge-blocking task, not a later perf finding. Sibling precedent (`007_program_releases_date_index.py`, promoted to ADR-0015; `008_program_team_index.py`, promoted to ADR-0016) is a plain additive `op.create_index(...)`, no `CONCURRENTLY` — this codebase has no deploy runbook/CI requiring a maintenance-window migration yet.

**Decision**: Add a new Alembic migration creating `ix_program_summary_tokens` on `program_summary(tokens)` (single-column, descending is implicit for a btree — Postgres can scan either direction). Mirrors `007_program_releases_date_index.py`'s pattern exactly: plain `op.create_index`, matching `downgrade()`, and the model's `__table_args__` + `tests/fixtures/prd_8_4_schema.json` updated in the same task so `TestSchemaDiffGate`/`TestFixtureDrivenTableConstraints` stay green. `blast:data` alone triggers the `decide` skill's promotion rule (`blast: is system or data` OR `rev: is effectively-irreversible` — an OR, not a requirement that both be severe), matching ADR-0015 and ADR-0016's own precedent of promoting their analogous single/composite-index-on-a-shared-table decisions. Promoted to `docs/adr/0017-program-summary-tokens-index.md`.

### D-02: Story-local pagination default (`page=1, page_size=20`, clamp 100) via a story-local `Query` dependency, not the shared `get_page_params` · blast:feature · rev:mechanical · adr:—

**Context**: `app/dependencies/pagination.py::get_page_params` defaults `page_size` to `MAX_PAGE_SIZE` (100), not 20 — using it verbatim would silently violate FR-2's `default 20, clamp 100` contract. The `_releases_offset_limit` precedent in `overview.py` (story-local wrapper reusing the shared `MAX_OFFSET_LIMIT` constant for the clamp) is the established way to override just the default without introducing a second clamp literal.

**Decision**: Add a story-local `_board_page_params(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1)) -> tuple[int, int]` in `overview.py`, clamping via `min(page_size, MAX_PAGE_SIZE)` (reusing the existing `app/dependencies/pagination.py::MAX_PAGE_SIZE` constant, not a new literal). `page`/`page_size` never 422-reject above the max (clamp precedent, FR-2) but DO 422 on `page < 1` or `page_size < 1` (`ge=1` on both — TC-10 requires this).

### D-03: `metrics` ships fixed `{glyph, label, value}` constants inline in the service module, not a shared cross-story registry · blast:feature · rev:mechanical · adr:—

**Context**: FR-1 (PO-resolved) requires `metrics` as an ordered 4-entry `[{glyph, label, value}]` array mirroring ADR-0007's `program-detail-api` `summary` shape. Unlike `program-detail-api`, this is not a registered cross-story contract in `docs/requirements/api.md` (`docs/stories/OVW-04.md` confirms `consumed_by: []`) — it is feature-internal.

**Decision**: Define `_BOARD_METRIC_GLYPHS_LABELS` as a fixed 4-tuple constant in `app/services/program_board.py` (mirroring `overview.py`'s existing `_ORG_SUMMARY_GLYPHS_LABELS` pattern): `(("⬡", "Total tokens"), ("⤴", "Releases via Harness"), ("✦", "Features via Harness"), ("⚇", "Active contributors"))`. `value` for each is `format_number()` of `tokens`/`releases`/`features`/`active_contributors` respectively, in that fixed order — order is the contract, never re-sorted.

### D-04: Drop `icon` derivation duty to the wire field already on `ProgramSummary.icon` — no client-side avatar-letter derivation added · blast:feature · rev:mechanical · adr:—

**Context**: DESIGN.md's own gap-3 recommended dropping `icon` and deriving the avatar letter via `programStyle.ts`, but the PO's binding resolution (REQUIREMENTS.md § Resolved questions #2) overrides that recommendation: `programStyle.ts::getProgramStyle()` derives colors only, never the abbreviation letter, and PGD-01 already ships `icon` verbatim from `program_summary.icon` (`ProgramDetailHeader.icon`).

**Decision**: `fetch_program_board()` passes `ProgramSummary.icon` through verbatim to the wire (`ProgramBoardCard.icon: str`), exactly like `ProgramDetailHeader.icon`. No new abbreviation-derivation logic anywhere. `programStyle.ts::getProgramStyle(type)` is reused for `avatarStyle`/`typeChip` colors only, client-side, per the presentation-vs-data boundary constraint.

### D-05: MoM `flat` chip token addition (`#5b6472` on `#f0f1f4`) recorded in `tokens.md`, not invented ad hoc in the component · blast:feature · rev:mechanical · adr:—

**Context**: REQUIREMENTS.md § Resolved questions #5 accepts DESIGN.md's conservative default for the one value the mockup's design source doesn't settle — the `flat`/`null` MoM chip. `docs/design/tokens.md` is the single documented home for hex values used across dashboards (per its own stated role and `programStyle.ts`'s comment convention).

**Decision**: Add the `flat` MoM pair (`#5b6472` text on `#f0f1f4` background) to `docs/design/tokens.md` alongside the existing `up`/`down` MoM pair, tagged as PO-approved-not-mockup-sourced (same disclosure style DESIGN.md uses). `ProgramCard.tsx` derives the chip's colors from this token entry via a small `momChipStyle(direction)` helper (mirroring `getProgramStyle`'s shape), not inline hex literals in the component.

### D-06: `program_drilldown` logged from the frontend navigation, not the backend route · blast:feature · rev:mechanical · adr:—

**Context**: The story's Observability NFR requires `program_drilldown` logged "when a program card's navigation affordance is selected" — a client-side interaction event, unlike the backend's own use of `program_drilldown` in PGD-01/PGD-06 (server-side, on a program-detail *fetch*). OVW-04's board endpoint itself does no per-program fetch to log against; the event fires on card click before navigation, which only the frontend observes.

**Decision**: `ProgramCard`'s anchor `onClick` (a lightweight client handler that does not block or delay navigation) posts a `program_drilldown` client-side telemetry call reusing whatever telemetry sink already exists for frontend events in this codebase (none exists yet as of OVW-01/PGD-01 — this reduces to a `console.info`-based structured log matching `JSONFormatter`'s field names, `{event: "program_drilldown", program_id}`, consistent with the backend's `logger.info("program_drilldown", extra={"program_id": ...})` shape at `overview.py:214`, until a real frontend telemetry pipe exists). This does not block or delay the `<a href>` navigation (native browser nav, no `preventDefault()`).
