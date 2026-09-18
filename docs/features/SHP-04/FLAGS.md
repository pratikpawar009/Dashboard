### AF-24: evidence-na · task: n/a · docs/config/project-commands.yaml
design_check dimension marked N/A — `design_check:` key is empty in project-commands.yaml. Reason: no a11y/console-error-scan/perf tool wired for this project yet (per that file's own comment); design integration is html-mockup with fileKey/url still TODO.

### AF-25: evidence-na · task: n/a · apps/web (nextjs runtime stack)
Frontend runtime render_check marked "unavailable" — boot-only evidence (GET / -> 307 -> /overview -> /login -> 200, clean boot log) was captured, but an actual browser-rendered mount check could not be completed: `@playwright/test` browser binaries exist in the local Playwright cache, yet the bare `playwright` package is not resolvable as a direct import from an ad hoc script in apps/web's module graph, and full `test_e2e` execution is deferred to /arh-validate-feature per project-commands.yaml's own comment. Recommend eyeballing the running app at http://127.0.0.1:3000/ (or via /arh-validate-feature's E2E pass) before treating the frontend as visually verified.

---

## Triage record — 2026-09-18, pre-commit

| Flag | Disposition |
|---|---|
| AF-24 | **Accepted as N/A.** `design_check` is deliberately empty in `docs/config/project-commands.yaml` — no a11y/console-scan tool is wired for this project yet, which that file's own comment records as an intentional, honest gap. Not an SHP-04 omission. Standing carry-forward until a tool is chosen and wired. |
| AF-25 | **Accepted as N/A.** Frontend `render_check` is boot-evidence only: Playwright browser binaries are not installed in this environment and `test_e2e` execution is deferred to `/arh-validate-feature` by project policy. The runtime dimension still passed on a real boot (clean 307 → 307 → 200 auth-redirect chain), and validation independently exercised the component suite (341 frontend tests) plus a live five-persona RBAC check against a running API. |

Review findings carried to the PR body rather than fixed here (both MEDIUM, neither a fix-loop trigger
under the gate's GREEN rule):

- **F-1** — the proxy folds a real `governance_visibility` 403 into `502 upstream_error`, since
  `ArtifactsResult` has no `forbidden` variant. This faithfully mirrors the shipped `team` proxy and is
  documented in both the route docstring and a dedicated test, and its blast radius is zero today
  because the component ships unwired. Worth an ADR-level decision — add a `forbidden` variant, or
  formally accept 502-for-403 — before ARC-01/DEV-01/PMD-01 compose real pages against it and more
  proxies inherit the shortcut.
- **F-2** — the five tag/colour constants live in `services/artifacts.py`, `tokens.md` and `DESIGN.md`
  with no automated cross-check. Consistent with the existing `_BOARD_METRIC_GLYPHS_LABELS` convention
  (tokens.md documents, Python owns at runtime), so not new drift — just an existing pattern with no guard.
- **F-3** (LOW) — `_ARTIFACT_PRESENTATION`'s ordered 5-tuple duplicates `_CANONICAL_ARTIFACT_TYPES`'
  unordered frozenset with no test asserting the two stay equal; a future sixth canonical type would
  silently not appear in the response. A cheap set-equality unit test would close it.

Also standing, unchanged from earlier stories: tag-chip contrast below WCAG AA on four of five pairs,
systemic to the design system's tint-on-tint recipe and already shipped as persona pills.
