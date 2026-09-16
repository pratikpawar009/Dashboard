### AF-01: `tagColor`/`tagBg` program-theme source is a new convention, not a reuse

- **kind**: risky-pattern
- **task**: T-04
- **source**: `services/api/app/services/program_releases.py` (`_TAG_PALETTE` / `_tag_colors_for_program`)
- **status**: resolved (orchestrator, 2026-09-16)

No existing code produces a `(tagColor, tagBg)` **pair** keyed by program. `app/utils/format.py::dot_style_for_program`
produces a single deterministic hex only. DESIGN.md § "CSS-bearing bindings" says these come from "the program's theme"
without naming a mechanism; D-02 and PLAN.md do not specify one either.

T-04 mirrored `dot_style_for_program`'s sha256-digest-into-a-fixed-palette approach with a 4-entry palette drawn from
existing design-token hues — deterministic and consistent with the codebase, but a **new** convention rather than a
reuse. A literal per-program config field, or a different palette, could be intended instead. Confirm against the
authored mockup / a human decision before ship.

**Resolution**: Extracted `dashboards/Program Detail.html` directly. The mockup keys `tagColor`/`tagBg`
off the **program's `type`** via its 4-entry `tMap` (`tMap[P.ptype] || tMap['Migration']`, passed into
`genReleases` as `t.c, t.bg`) — the same colour pair that drives the program avatar and type chip, NOT a
per-program hash. Authoritative hexes live in `docs/design/tokens.md` § Program type colors and are
already implemented frontend-side at `apps/web/src/lib/programStyle.ts`. T-04 was corrected: the invented
`_TAG_PALETTE`/sha256 approach was deleted and replaced with `_PROGRAM_TYPE_TAG_COLORS` mirroring that map
(long-form entries + `Greenfield`/`Brownfield` short aliases, `Upgradation` deliberately unmapped, unknown
type falling back to `Migration` without raising). No human decision outstanding.

### AF-02: PLAN/PRD say "structlog"; the codebase has none — stdlib `logging` used instead

- **kind**: plan-drift (naming only)
- **task**: T-05
- **source**: `services/api/app/api/overview.py` (releases route completion log)
- **status**: resolved (orchestrator, 2026-09-16) — no action needed

PGD-03's PRD (§ Non-functional / Observability) and `tasks.json` T-05 notes both say the request log is
emitted "via `structlog`". No structlog dependency or import exists anywhere under `services/api/**`.
T-05 therefore emitted the completion log through the codebase's actual idiom — stdlib
`logging.Logger.info(event, extra={...})` with a `time.perf_counter()` latency measurement, matching
`app/api/admin.py` — per `.claude/rules/pattern-consistency.md`.

This is confirmed pre-existing, documented drift, not a new inconsistency: `services/api/tests/conftest.py:901-904`
already records that the `structlog_capture` fixture "hooks the STDLIB `logging` module, not structlog …
there is no structlog anywhere under `services/api/**`". The word is vestigial in this project's prose.
The log carries every required field (method, path, program_id, range, offset, limit, status, latency).
No new dependency should be introduced for this story.

### AF-03: `design_check` evidence dimension is N/A — no tool wired project-wide

- **kind**: evidence-na
- **task**: n/a (evidence pass)
- **source**: `docs/config/project-commands.yaml` (`design_check: ""`)
- **status**: triaged — accepted as N/A (engineer, 2026-09-16)

The `design_check` key exists but is empty: no accessibility / console-error-scan / perf tool has been
declared or installed for this project yet. `project-commands.yaml` documents this as deliberate and
honest rather than an oversight. Pre-existing project-wide gap, not specific to PGD-03 — every story
since scaffold has hit it. Closing it means choosing and wiring a tool (e.g. axe-playwright or pa11y-ci
against `apps/web`), which is out of this story's scope.

### AF-04: `runtime` evidence is boot-only for the web stack — Playwright browsers not installed

- **kind**: evidence-na
- **task**: n/a (evidence pass)
- **source**: `docs/config/project-commands.yaml` (preflight note)
- **status**: triaged — accepted as N/A (engineer, 2026-09-16); browser-level checks deferred to /arh-validate-feature

`@playwright/test` is installed as a devDependency but its browser binaries are not downloaded locally —
`project-commands.yaml`'s preflight deliberately defers that to `/arh-validate-feature`. So the runtime
dimension recorded boot-only evidence for the web stack (clean boot, `/` → 307 `/overview`) rather than a
render-mount check of the Releases panel in a real browser.

Backend runtime evidence IS full end-to-end: the API migrated to head `007`, booted clean, and the new
`GET /api/overview/program-detail/{program_id}/releases` route was smoke-tested to a 200 with its
structured completion log.

Note this intersects the story's own deferred coverage: TC-12/TC-13/TC-14 remain `automatable: false`
(PLAN.md § 7), and the `max-height:296px` scroll-container rendering is exactly the kind of visual
assertion only a real browser settles. `/arh-validate-feature` runs Playwright itself.
