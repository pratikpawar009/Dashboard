## AF-01 — AC-5 error badge + aria-live announcement cannot render on `/programs/[program_id]`

**Raised by:** T-08 (page test harness). **Verified by:** orchestrator, against source.

**Finding.** AC-5 requires that on a `403` / unrecognized persona, the neutral gray
"Persona unavailable" badge renders in place of the persona tag, plus a visually-hidden
`aria-live="assertive"` announcement "Unable to load your dashboard view."

That markup exists in exactly two places in `PersonaDashboardShell.tsx`:

- `PersonaHeader` (line 157) — gated on `!isLoading && program !== undefined`
- `renderOrgHeaderContent` (line 164, badge at 241-245) — gated on
  `!isLoading && pageTitle !== undefined && program === undefined`

`ProgramDetailView.tsx:163` passes `program={undefined}` (required by AC-2, so
`ProgramDetailHeader` does not double-render) and passes **no** `pageTitle`. Neither header
region therefore mounts on this route, and the badge/announcement are unreachable.

**Observed behaviour instead.** The sentinel correctly reaches the shell (FR-3 holds; proven by
`PGD-07-FR-3-TC-01`), and the identity block falls back to its D-05 neutral avatar — a silent,
`aria-hidden` gray circle. A persona-resolution failure is thus **not announced to assistive
technology at all** on Program Detail.

**Why the plan missed it.** AC-2 and AC-5 are individually satisfiable but jointly unsatisfiable
without changing `PersonaDashboardShell`, which REQUIREMENTS.md § Scope "Out:" freezes. No plan
task owns this conflict.

**RESOLVED 2026-09-16 — scope widened on explicit user authorization.** The user was presented
with carry-forward / fix-here / stop-and-re-spec and chose to fix it here, accepting the widened
scope into `PersonaDashboardShell` (an OVW-05-owned, PRD-frozen file).

**Fix.** The identity block now renders the same neutral badge + `aria-live="assertive"`
announcement, keyed on the existing `personaColor === null` signal, guarded on
`program === undefined && pageTitle === undefined` so it fires ONLY where neither header region
mounts. A route that renders either header keeps that region's badge as the single copy.

The guard is load-bearing, not defensive: without it the badge rendered **twice** on `/overview`
and on the org-header variant, breaking `SHP-01-TC-02` and OVW-05 `AC-8/AC-9/AC-10`. Those three
regressions were caught by the existing suite and are green again.

`page.test.tsx`'s two assertions that documented the bug (badge absent, no `aria-live`) were
inverted to pin the corrected behaviour.

**Verification:** 184/184 tests pass across 31 files; `tsc --noEmit` clean.

**Carry-forward for OVW-05's owner:** the shell now has two badge render paths. If the header
regions are ever refactored, the identity-block fallback's guard must be revisited with them.

**Affects:** AC-5, test cases `PGD-07-TC-06`, `PGD-07-TC-07`.

### AF-02: evidence-na · task: n/a · docs/config/project-commands.yaml

`design_check` dimension marked N/A during the PGD-07 evidence pass — `design_check:` key is
empty in `docs/config/project-commands.yaml`. No a11y/console-error-scan/perf tool has been
declared or wired for this repo yet (documented as deliberate in the config file's own comment);
consistent with the precedent in other features' `impl_evidence` (e.g. BED-01).

### AF-03: evidence-na · task: n/a · apps/web (no E2E/browser tooling)

`runtime` dimension's frontend (`nextjs`) stack entry: boot-only evidence collected (`/`, `/login`,
`/overview`, `/programs/[program_id]` all returned the expected HTTP codes — 307 redirects to
`/login` for the three protected routes, 200 for `/login` itself carrying the expected brand
markup — and the boot log has no `Error|Exception|Panic|FATAL` matches). `render_check` is
`"unavailable"`: no Playwright/Cypress/Puppeteer is installed in `apps/web/package.json`, and
`docs/config/project-commands.yaml`'s `test_e2e:` is empty ("not yet configured — no e2e framework
declared in ADR-0001"), so an actual client-mount assertion beyond boot+redirect could not be
captured. Flagging per `evidence-pass` skill's frontend runtime rule so `/arh-human-review` can
eyeball the running app if desired.
