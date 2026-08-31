# AUTH-04 — Decisions

Decision log for `GET /api/programs`. ADR-0005 (response shape, C-0) was decided at the
research/PRD gate and is not re-litigated here — see `docs/adr/0005-programs-api-switcher-shape.md`.
The two entries below are planning-time decisions this phase makes.

### D-01: `dotStyle`'s per-program colour is a server-side deterministic palette function, not a `program_summary` column · blast:feature · rev:mechanical · adr:—

**Context**: ADR-0005 § Flagged gaps leaves the source of `dotStyle`'s per-program colour open:
a `program_summary` column, or a server-side palette assignment keyed on `program_id`.
`app/models/rollup.py::ProgramSummary` (BED-01, locked schema) has `icon: str` (an icon-name
enum, not a colour) and no colour/style column. Adding one needs an Alembic migration and a
BED-01 schema-owner sign-off; the org's scale (~9 programs today, ~100 at the C-4 perf
baseline) needs no persisted state at all to assign a stable colour per program.

**Decision**: `dot_style_for_program(program_id: str) -> str` in `app/utils/format.py` hashes
`program_id` into a fixed, small CSS-colour palette and returns a ready-to-bind CSS value
(e.g. `"background-color: #4F46E5;"`) — deterministic across requests/workers/restarts (no
cache, no TTL, no migration). Reversible: swapping to a `program_summary.dot_color` column
later touches one call site in `app/api/programs.py`, additive for existing consumers.

### D-02: Router module path corrected to `services/api/app/api/programs.py` (story's `backend/app/routers/programs.py` is stale) · blast:feature · rev:mechanical · adr:—

**Context**: `docs/stories/AUTH-04.md` § Decision log (2026-08-26) names the module path
`backend/app/routers/programs.py`, citing "AUTH-01/BED-04 story precedent" — no `backend/`
directory or `routers/` package exists anywhere in this repo. The real layout is
`services/api/app/api/<resource>.py` (`health.py`, `ingest.py`, `activities.py`). The story is
`Status: Validated`; per the same non-reopening rule ADR-0005 already applied to AC-5, the story
file is not edited — this decision carries the correction forward.

**Decision**: the router lives at `services/api/app/api/programs.py`,
`router = APIRouter(prefix="/api/programs", tags=["programs"])`, matching the existing
per-resource-module convention and `docs/requirements/api.md#programs-api`'s literal
`GET /api/programs` endpoint.
