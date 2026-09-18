# SHP-03 — Decisions

Decision log for the personal session-wise usage list. Header carries `blast:`/`rev:`/`adr:` slugs for greppable audit.

### D-01: New `format_session_duration()` alongside `format_duration()`, not a change to the shared function · blast:feature · rev:mechanical · adr:—

**Context**: `app/utils/format.py::format_duration()` is a sealed cross-story contract (its own module docstring calls it "the authoritative boundary contract", BED-02-TC-12 pins its boundaries, and it's consumed by SHP-02/PGD-04/PGD-05 today). Its shape is `"2h 5m"` / `"2h"` / `"5m"` (no zero-pad, drops the minutes term on exact hours) — DESIGN.md's generator requires `"2h 07m"` (minutes always shown, zero-padded to 2 digits, hours never padded). The two contracts genuinely disagree; editing the shared function would silently change SHP-02/PGD-04/PGD-05's output.

**Decision**: Add a new pure function `format_session_duration(duration_seconds: int) -> str` to `app/utils/format.py`, sitting beside `format_duration()` (same module, no new file — same-concern DRY per `.claude/rules/reusability-baseline.md`). It takes raw seconds (matching `user_sessions.duration_seconds`'s unit, avoiding a minutes-conversion step `format_duration` requires), and renders `f"{h}h {m:02d}m"` unconditionally (both terms always present, minutes zero-padded, hours not). `format_duration()` itself is untouched.

### D-02: New `format_session_tokens()` alongside `format_number()`, not a change to the shared function · blast:feature · rev:mechanical · adr:—

**Context**: `format_number()` is also a sealed boundary contract with its own promotion/rounding rules, consumed by every other card/series in the codebase, and its K/M output (`"2.5K"`, `"1.0M"`) already matches DESIGN.md's `tokens` format almost exactly — but `format_number()`'s sub-1000 branch renders a bare int (`"999"`) with no suffix, and DESIGN.md's generator has no such branch (`tk >= 1 ? ... : Math.round(tk*1000)+'K'` — the mockup's `tk` is already in millions, so its only two branches are M and K; there is no observed no-suffix path in the design source, and the row anatomy table lists only `"1.2M"`/`"840K"` as examples). Reusing `format_number()` outright risks a sub-1000 session (an extremely low-token session) rendering as a bare `"850"` where the design's own generator would never produce a suffix-less value at all.

**Decision**: Add `format_session_tokens(tokens: int) -> str` to `app/utils/format.py`, sitting beside `format_number()`. Delegates to `format_number()` for the M/K magnitude/rounding logic (no duplicated bucket math — DRY) but is a distinct named function so a future edit to `format_number()`'s sub-1000 behavior cannot silently change this panel without being noticed at this call site. For the sub-1000 case (below `format_number()`'s K threshold), renders `f"{round(tokens):d}K"` scaled as `tokens/1000` rounded to nearest int with a trailing `K` (i.e. always carries a K/M suffix, matching the generator's two-branch shape) rather than falling through to `format_number()`'s bare-int branch — this is a genuine, documented behavioral difference from `format_number()`, not a copy-paste.

### D-03: `meta` composed server-side from `session_identifier` + `started_at`, no raw-field siblings · blast:feature · rev:mechanical · adr:—

**Context**: DESIGN.md D-1 establishes the mockup binds one composite `meta` string, never `session_identifier`/`started_at` separately. Unlike `DailyTokenPoint.tokens` (ADR-0009 amendment) or `CommandEntry.count`, nothing downstream needs `session_identifier`/`started_at` as raw values — this is a terminal display surface, not a chart/bar-width input (REQUIREMENTS.md FR-1).

**Decision**: `PersonalSessionEntry` ships exactly 4 string fields (`title`, `meta`, `duration`, `tokens`) with `extra="forbid"`, mirroring `ArtifactItem`'s locked-field precedent (SHP-04 D-05/artifacts-api). `meta` is built as `f"S-{session_identifier} · {started_at:%b %-d, %Y}"` (U+00B7 middle dot, space-padded, year included) in the service layer — never exposed as two fields.

### D-04: RBAC gate call mirrors `personal_usage.py`'s bare-await pattern exactly, no new logging · blast:feature · rev:mechanical · adr:—

**Context**: `individual_usage_visibility(current_user, user_id)` already logs `individual_view_denied` on denial only, inside the gate itself (AUTH-03-FR-2). SHP-04 D-01 established the precedent of NOT adding a second route-level log around an already-self-logging gate, to avoid double-logging the same denial.

**Decision**: `GET /{user_id}/sessions` calls `await individual_usage_visibility(current_user, user_id)` as its first statement, bare, no try/except, no additional log line — identical shape to the existing `get_personal_usage()` handler in the same file.

### D-05: `personal-sessions-api` contract shape filled in `docs/requirements/api.md`, not duplicated in `DATA-DESIGN.md` § 9 · blast:feature · rev:mechanical · adr:—

**Context**: `personal-sessions-api` is a registered cross-story contract (`docs/requirements/api.md` § `personal-sessions-api`, `produced_by: SHP-03`, `consumed_by: [ARC-01, DEV-01, PMD-01]`) currently holding only a decomposition-time sketch (`fields: "session name/description, identifier, date, duration, tokens — paginated"`). Per `plan-authoring` step 10, the concrete shape is authored once in the shared registry; `DATA-DESIGN.md` § 9 carries only a bookmark.

**Decision**: Replace the `personal-sessions-api` sketch in `docs/requirements/api.md` with the concrete FR-1 wire shape (exact 4-field response, `page`/`page_size`/`total` raw ints, clamp-not-reject pagination, 403/empty-list cases). `DATA-DESIGN.md` § 9 points at it via `Contract: personal-sessions-api → docs/requirements/api.md#personal-sessions-api`.

### D-06: Frontend `SessionsTable` ships as a standalone component (mirrors SHP-04's `ArtifactsPanel` precedent) — not wired into any dashboard page · blast:feature · rev:mechanical · adr:—

**Context**: DESIGN.md specifies a `SessionsTable` component but the panel is embedded in ARC-01/DEV-01/PMD-01 — three dashboard-composition stories that do not exist yet (`REQUIREMENTS.md` § Scope Out: "dashboard composition beyond this one table"). SHP-04 (`docs/features/SHP-04/DECISIONS.md` D-04) is the exact same shape — a shared panel embedded in the same three not-yet-built dashboards — and its resolution was to ship the component + server-fetch lib + client-fetch lib + proxy route standalone, tested in isolation, with zero page-composition wiring owned by that story.

**Decision**: Follow the SHP-04 precedent exactly. Ship `apps/web/src/components/SessionsTable.tsx` (`"use client"` self-fetching, loading/empty/populated/error state machine per DESIGN.md D-4/D-5), `apps/web/src/lib/personalSessionsApi.ts` (server-only, direct-to-FastAPI), `apps/web/src/lib/personalSessionsApi.client.ts` (client-only, targets the proxy route), and `apps/web/src/app/api/proxy/personal-sessions/[user_id]/route.ts` (full server-to-server proxy per ADR-0008). No dashboard page imports `<SessionsTable>` in this story; ARC-01/DEV-01/PMD-01 each own mounting it, consistent with `REQUIREMENTS.md` § Scope Out and the SHP-04 D-04 precedent.

### D-07: `#4a5261` duration-cell color mapped to `text-700` (`#5b6472`) at implementation time, not added as a new token · blast:feature · rev:mechanical · adr:—

**Context**: DESIGN.md's own § Tokens used flags `#4a5261` as absent from `docs/design/tokens.md`'s color list, "sitting between `ink` and `text-700`", and explicitly leaves the resolution "not decided here." Adding a new design-system token is a six-dashboard-blast-radius decision belonging to whoever owns `docs/design/tokens.md`, not a call this single backend-anchored story should make unilaterally (mirrors SHP-04 D-... R-06's identical "token-level decision, not this story's to make" reasoning).

**Decision**: Implementation maps the duration cell to the nearest existing token, `text-700` (`#5b6472`) — visually closest of the two options DESIGN.md names ("between `ink` and `text-700`") and already used elsewhere on the same panel family. Carried forward as an accepted risk (§ 6) rather than blocking on a token-registry change.
