# SHP-04 — Decisions

Decision log for the Artifacts generated panel story. Header carries `blast:`/`rev:`/`adr:` slugs for greppable audit.

### D-01: No separate `governance_view_denied` event — supersedes story Decision log · blast:feature · rev:mechanical · adr:—

**Context**: The story's own Decision log (`docs/stories/SHP-04.md`) names a `governance_view_denied` event, assumed by analogy with `individual_view_denied`/`member_view_denied`. Research and `REQUIREMENTS.md` SHP-04-FR-2 confirm `governance_visibility` (`services/api/app/core/rbac.py:196-243`) already emits `rbac_check_governance_visibility` with an `outcome` field on both the authorized and denied paths, and raises the `403` itself — before any `program_artifacts` read. A route-level event would double-log the same denial.

**Decision**: `app/api/artifacts.py` adds zero logging around the `governance_visibility` dependency call, matching the no-additional-logging precedent in `personal_usage.py`/`overview.py`. The story's `governance_view_denied` entry is superseded; do not implement it.

### D-02: `governance_visibility` wired as a bare awaited call inside the handler, not a FastAPI `Depends()` · blast:feature · rev:mechanical · adr:—

**Context**: `governance_visibility(current_user, program_id)` takes `program_id` from the path, which is only available once FastAPI resolves the route parameters. `personal_usage.py`'s `individual_usage_visibility` gate uses the identical pattern — a bare `await` inside the handler body, not a `Depends()` wrapper — because the check needs the resolved path/query values directly, not a second dependency-injection indirection.

**Decision**: Mirror `personal_usage.py`'s exact shape: `await governance_visibility(current_user, program_id)` as the handler's first statement, before any `program_artifacts` read. This is also this gate's first live route consumer (research risk R-08/PGD precedent), so the route docstring calls that out explicitly per `REQUIREMENTS.md` § Documentation requirements.

### D-03: Zero-fill happens in the service layer via a fixed presentation-constants tuple, mirroring `program_commands.py`'s module-constant idiom · blast:feature · rev:mechanical · adr:—

**Context**: `SHP-04-FR-1` fixes `items` at exactly 5 entries, fixed order, server-owned `tag`/`name`/`bg`/`color` per canonical type — a flat, non-derived mapping (`DESIGN.md` § Presentation constants: "a flat literal array, not a derivation"). `program_board.py`'s `_BOARD_METRIC_GLYPHS_LABELS` and `overview.py`'s `_ORG_SUMMARY_GLYPHS_LABELS` are the established precedent for a fixed presentation-constant tuple owned by the service module, not a shared registry or DB-stored config.

**Decision**: `app/services/artifacts.py` defines `_ARTIFACT_PRESENTATION: tuple[tuple[str, str, str, str, str], ...]` — one 5-tuple `(canonical_type, tag, name, bg, color)` per row, in `_CANONICAL_ARTIFACT_TYPES` order, values transcribed verbatim from `DESIGN.md` § Presentation constants. `fetch_program_artifacts()` queries `program_artifacts` for the given `program_id` into a `dict[str, int]` keyed by `type`, then iterates `_ARTIFACT_PRESENTATION` in fixed order, looking up each type's count with `.get(canonical_type, 0)` — this is what produces both the empty-program zero-fill (AC-3) and the real-persisted-zero passthrough (AC-4) via the same code path, with no special-casing between "missing row" and "row with count=0".

### D-04: Frontend `ArtifactsPanel` ships as a small presentational component with a server-fetch lib + client-fetch lib + proxy route, matching `ProgramTeamPanel`'s three-file split, but is not wired into any page by this story · blast:feature · rev:mechanical · adr:—

**Context**: `REQUIREMENTS.md` § Scope explicitly excludes "dashboard composition beyond this one panel" — ARC-01/DEV-01/PMD-01 own mounting the component into their respective pages, which do not exist yet. `ADR-0008` requires every cross-service fetch to go through a server-only lib (direct-to-FastAPI) plus a same-origin `/api/proxy/*` Route Handler for client components — no route hands an access token to client-side JS. `ProgramTeamPanel.tsx` + `programTeamApi.ts` + `programTeamApi.client.ts` + the proxy route is the exact precedent for a self-fetching client panel with no page composition owned by the same story (PGD-05 shipped the panel; the pages consuming it were separate stories).

**Decision**: Ship `apps/web/src/components/ArtifactsPanel.tsx` (a `"use client"` self-fetching component, mirroring `ProgramTeamPanel`'s loading/error/populated state machine but with no range toggle — this panel has none per `DESIGN.md`), `apps/web/src/lib/artifactsApi.ts` (server-only, direct-to-FastAPI, mirrors `programTeamApi.ts`), `apps/web/src/lib/artifactsApi.client.ts` (client-only, targets `/api/proxy/artifacts/[program_id]`, mirrors `programTeamApi.client.ts`), and `apps/web/src/app/api/proxy/artifacts/[program_id]/route.ts` (full server-to-server proxy, mirrors `program-detail/[program_id]/team/route.ts`). No dashboard page imports `<ArtifactsPanel>` in this story — that wiring belongs to ARC-01/DEV-01/PMD-01, consistent with `REQUIREMENTS.md` § Scope Out.

### D-05: `artifacts-api` contract shape filled in `docs/requirements/api.md`, not duplicated in `DATA-DESIGN.md` § 9 · blast:feature · rev:mechanical · adr:—

**Context**: `artifacts-api` is a registered cross-story contract (`docs/requirements/api.md` § `artifacts-api`, `produced_by: SHP-04`, `consumed_by: [ARC-01, DEV-01, PMD-01]`) with a placeholder decomposition-time sketch. Per `plan-authoring` step 10, a registered contract's concrete shape is authored once in the shared registry; `DATA-DESIGN.md` § 9 carries only a bookmark.

**Decision**: Replace the `artifacts-api` sketch in `docs/requirements/api.md` with the concrete `SHP-04-FR-1` wire shape (exact field names, fixed order, server-owned constants, raw-int `count`). `DATA-DESIGN.md` § 9 points at it via `Contract: artifacts-api → docs/requirements/api.md#artifacts-api`.
