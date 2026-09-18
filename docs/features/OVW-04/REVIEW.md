# Code Review — feature/OVW-04 (round 2, snapshot a06db803)

- Date: 2026-09-18
- Mode: story (GATE MODE — report-only)
- Files reviewed (delta only): 2 new (`ProgramCardLink.tsx`, `overview-program-board.spec.ts`), 1 edited (`ProgramCard.tsx`)
- Verdict: PASS

## Executive summary

The delta is a scoped RSC-boundary fix: `ProgramCardLink.tsx` (new, `"use client"`) now owns the root `<a>` and D-06's `program_drilldown` click handler; `ProgramCard.tsx` stays a Server Component and renders `<ProgramCardLink>` instead of attaching `onClick` to its own `<a>`. A new Playwright spec asserts `/overview` returns 200 against a real Next.js server. The extraction is minimal and correctly reasoned: `ProgramCardLink` imports nothing but `react` types and the shared CSS module — `ProgramSparkline`, `getProgramStyle`, and `momChipStyle` stay in the server-rendered parent and are never pulled into the client bundle. The client/server split matches the codebase's own precedent (`ProgramSwitcher.tsx`: small `"use client"` interactive leaf under a larger, non-`"use client"` composition), and correctly distinguishes it from `ProgramDetailView.tsx`, which is a full Client Component because it owns real mutable state (`useState`/`useRouter`) — not a comparable shape. Every prop contract, the T-12 fix, and accessibility properties (`aria-label`, real `<a href>`, no `preventDefault()`) are unchanged and re-verified by the existing `ProgramCard.test.tsx`. The new e2e spec is a real regression guard, not a vacuous pass — its assertions (HTTP 200, not 500; a rendered, keyboard-reachable link) fail against the pre-fix component and only pass because the RSC boundary is now respected; it earns its place despite not being executed this session (browser binaries absent, execution correctly deferred to `/arh-validate-feature` per project policy — `playwright test --list` discoverability is the author-time bar, consistent with the `program-token-trend.spec.ts` precedent it cites).

🟢 Correct, minimal client/server split; matches local precedent; a11y and prop contracts fully preserved; e2e spec is a genuine regression guard, not a false-positive test.
⚠️ D-06 telemetry relocation doesn't change round-1 LOW F-1's assessment (still decision-sanctioned, still `console.info`, now doubly true it's client-only).
🛑 None.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL |   0   | — |
| HIGH     |   0   | — |
| MEDIUM   |   0   | — |
| LOW      |   2   | design-patterns (1, carried from round 1), integration (1, carried from round 1) |

## Delta-specific assessment

### 1. Client/server split — correct and minimal

`ProgramCardLink.tsx` imports only `type { CSSProperties, ReactNode } from "react"` and `./ProgramCard.module.css`. It receives `href`, `programId`, `borderLeftColor`, `ariaLabel`, and `children` as props — no data-shaping logic, no `ProgramBoardCardData` dependency. `ProgramCard.tsx` retains every import that does real work (`getProgramStyle`, `momChipStyle`, `ProgramSparkline`) and computes `avatarStyle`/`typeChip`/`chipStyle`/`repoLabel`/`repoPct` server-side, passing only primitives (a color string, an aria-label string, a href string) across the boundary as props — not JSX, not a style object with the full `avatarStyle` record. This is the minimal interactive surface: nothing that could stay server-rendered was pulled into the client leaf. The author's stated alternative (marking the whole card `"use client"`) would have shipped `ProgramSparkline`'s SVG-generation logic and both style-lookup modules to the browser for up to 20 cards per page load — verified true given `ProgramSparkline`/`getProgramStyle`/`momChipStyle` are imported exclusively by `ProgramCard.tsx`, not `ProgramCardLink.tsx`.

### 2. Local precedent — confirmed

`ProgramSwitcher.tsx` is `"use client"` and owns only interactive concerns (open/closed disclosure, click handlers) while its own inline-style derivation (`dotStyleToInlineStyle`) is a pure function, not evidence against the pattern — it's still a small, fully client-owned leaf, matching `ProgramCardLink`'s shape (small client leaf, parent stays server). `ProgramDetailView.tsx` is correctly identified as non-comparable: it opens with `useState`/`useRef`/`useEffect`/`useRouter` and owns real client-side mutable state (program-switcher open state, fetched detail data, loading flags) — a fundamentally different reason to be a Client Component than "needs one click handler." The round-2 reasoning holds up against the actual source, not just the PR's stated claim.

### 3. D-06 telemetry — round-1 F-1 status unchanged

Round-1 F-1 flagged `console.info(JSON.stringify(...))` as a real-but-temporary mechanism, decision-sanctioned by D-06, non-blocking. Moving the call site from `ProgramCard.tsx` into `ProgramCardLink.tsx` changes nothing about that assessment: it is still `console.info`, still fires synchronously on click with no `preventDefault()`, still matches the backend's `JSONFormatter` field shape per D-06's decision text, and remains equally (un)observable in production. `ProgramCard.test.tsx`'s existing "logs program_drilldown on click without preventing navigation (D-06)" test still asserts against the same behavior, now indirectly through the composed `ProgramCardLink`, and still passes. **F-1 is RESTATED, not resolved, not worsened** — same LOW severity, same suggested follow-up (real telemetry sink).

### 4. Playwright spec — earns its place

The spec's own assertion (`response?.status()` must be `200`, not the pre-fix `500`) is discriminating: against the pre-fix `ProgramCard.tsx` (root `<a onClick>` with no `"use client"` ancestor), Next.js's RSC serialization raises "Event handlers cannot be passed to Client Component props" and the real page 500s — this spec would fail on that commit. It would not have silently passed while the page was broken. The file's own doc comment correctly identifies why vitest/jsdom structurally cannot catch this class of defect (jsdom renders the component tree directly, bypassing RSC payload serialization entirely) — this is not a redundant test, it covers a boundary no other test in the suite touches. Non-execution this session (no Playwright browser binaries, `--list`-only discovery) is consistent with declared project policy (`docs/config/project-commands.yaml` `test_e2e` comment: "execution deferred to `/arh-validate-feature`") and with the pre-existing `program-token-trend.spec.ts` precedent it explicitly follows.

### 5. Regression check — none found

- Prop contract: `ProgramCardLink`'s `{href, programId, borderLeftColor, ariaLabel, children}` matches exactly what `ProgramCard.tsx` passes; no prop dropped or renamed.
- T-12 fix: untouched by this delta — no changes to `programBoardResult` handling in this diff.
- Accessibility: the rendered `<a>` still carries `aria-label={`${card.name} — open program detail`}`, a real `href`, and no `tabIndex`/role override — still natively keyboard-reachable, confirmed by `ProgramCard.test.tsx`'s "is keyboard reachable" test, unchanged and still passing against the new composition.
- No other files in the round-1 scope were touched by this delta.

## What went well (round 2, delta only)

- Root-caused the actual defect (RSC event-handler boundary violation) rather than a workaround (e.g., wrapping the whole tree in `"use client"`, which would have worked but traded correctness for unnecessary bundle bloat).
- Extraction stayed surgical — `ProgramCard.tsx`'s diff is a swap from `<a onClick=...>` to `<ProgramCardLink>`, not a rewrite of surrounding card markup.
- New e2e spec's own doc comment does the reviewer's job for them: explains root cause, explains why unit tests missed it, explains why this test type is the only one that could catch it.

## Recommendation

PASS. No CRITICAL/HIGH/MEDIUM findings in the delta. Round-1's two LOW findings are re-stated, unchanged in status: F-1 (`console.info` telemetry, decision-sanctioned, now in `ProgramCardLink.tsx:39`) and F-2 (no cache/TTL doc note on `program_summary` reads, `services/api/app/services/program_board.py:142-166`, out of scope for this delta — unchanged since round 1). Both remain non-blocking follow-ups for the PR body.
