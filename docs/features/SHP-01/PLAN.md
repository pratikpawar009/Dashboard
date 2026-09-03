# PLAN: SHP-01 — Persona header/context shell

Status: Complete

**Design source**: `docs/features/SHP-01/DESIGN.md` does not exist — `ux-agent` is not installed in this repo (`state.json` `design: pending`, PRD Approvals table). UI tasks below are planned against the PRD's `## Screen inventory`, the decoded persona mockups (`arc`/`dev`/`pmd`/`emd.doc.html`, per `docs/design/README.md`'s decode procedure), and `docs/design/tokens.md` — not a placeholder DESIGN.md. Every literal string, hex color, and pixel size cited in this plan and in `tasks.json` was cross-checked directly against that decoded markup.

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Five entries (D-01..D-05), all `blast:feature` / `rev:mechanical` — none promoted to a full ADR: D-01 (the FR-1 field-name isolation adapter, `apps/web/src/types/persona.ts`), D-02 (`formatPersonaTag()` bundles tag+subtitle+color+background into one call), D-03 (a single `persona` prop unifies `cio` and a resolver-error sentinel into one fail-loud path), D-04 (persona and program-type color pairs added to `docs/design/tokens.md`, sourced from the decoded mockups), D-05 (the identity-bar neutral fallback markup when `signedInUser` is `undefined` post-resolution).

`nextjs-patterns`/`typescript-patterns` are filled skill bodies for this repo (G15) — this plan follows their concrete conventions (App Router Server Components by default, CSS Modules co-located per component, `@/*` path alias, `strict: true`) rather than generic React advice. Where the codebase has no precedent yet (no `src/components/` or `src/lib/` exist before this story), this plan falls back to Next.js's own idiomatic defaults and says so plainly, per `.claude/rules/pattern-consistency.md`.

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`. 15 files, all under `apps/web/src/` except one (`docs/design/tokens.md`, modified): 3 new types/lib-map files, 2 more lib files, 3 components + 2 CSS Modules files, 4 test files, 1 tokens.md extension.

### Module hierarchy

```
apps/web/src/
├── types/
│   └── persona.ts                                       (new)
│       - input:  none — pure type/const declarations
│       - output: SignedInUser, ProgramContextData, Persona, VALID_PERSONAS
│       - public: interface SignedInUser { name: string; jobTitle: string }
│                 interface ProgramContextData { icon; name; type; description }
│                 const VALID_PERSONAS = [...4 personas] as const
│                 type Persona = string
│                 (D-01 — the FR-1 isolation adapter: only this file and
│                 PersonaDashboardShell.tsx reference signedInUser's field names)
├── lib/
│   ├── formatPersonaTag.ts                               (new)
│   │   - input:  persona: Persona
│   │   - output: { tag, subtitle, color, background } | throws PersonaTagError
│   │   - public: class PersonaTagError extends Error
│   │             function formatPersonaTag(persona) -> {tag,subtitle,color,background}
│   │             (D-02; sources its literal map from docs/design/tokens.md
│   │             § Persona colors)
│   ├── deriveInitials.ts                                 (new)
│   │   - input:  name: string
│   │   - output: string (1-2 uppercase letters)
│   │   - public: function deriveInitials(name) -> string
│   └── programStyle.ts                                   (new)
│       - input:  type: string  (program.type)
│       - output: { avatarStyle, typeChip }
│       - public: function getProgramStyle(type) -> {avatarStyle, typeChip}
│                 (D-04; sources its literal map from docs/design/tokens.md
│                 § Program type colors)
└── components/
    ├── PersonaHeader.tsx + .module.css                   (new)
    │   - input:  { persona: Persona }
    │   - output: tag+subtitle pill, OR neutral "Persona unavailable" badge
    │              + aria-live="assertive" announcement
    │   - public: function PersonaHeader({ persona }): JSX.Element
    │              (calls formatPersonaTag internally; never receives `undefined` —
    │              PersonaDashboardShell only mounts it past the loading gate)
    ├── ProgramContext.tsx + .module.css                  (new)
    │   - input:  { program: ProgramContextData }
    │   - output: icon/name/type-chip/description, verbatim + shell-composed style
    │   - public: function ProgramContext({ program }): JSX.Element
    │              (calls getProgramStyle(program.type) internally; never reads
    │              a style field off the prop, even if present — FR-4/C-5)
    └── PersonaDashboardShell.tsx + .module.css           (new)
        - input:  { signedInUser?: SignedInUser; persona?: Persona;
                    program: ProgramContextData }
        - output: full 3-region shell render, gated by FR-5's 3 states
        - public: function PersonaDashboardShell(props): JSX.Element
                  (composes PersonaHeader + ProgramContext; owns the
                  loading gate, the inline identity block, and the
                  identity-bar neutral fallback — D-01, D-03, D-05)
```

No navigation/routing map — this story adds no route (Screen inventory: all three regions render `server` inside whichever route ARC-01/DEV-01/PMD-01/EMD-01 eventually own; none of those routes exist yet). `PersonaDashboardShell.tsx` has no in-repo consumer today — see § 6 Cross-Feature Dependency Notes for why that is a documented story boundary, not a wiring gap.

## 3. Module Hierarchy

See the tree in § 2 above — file plan and hierarchy are documented together since every new file in this story belongs to the same small, newly-created `apps/web/src/{types,lib,components}/` surface (none of those directories exist yet). Every `create` file's consumer is either another file created in this same plan (imported directly at authoring time — `formatPersonaTag`→`PersonaHeader`/`PersonaDashboardShell`; `programStyle`→`ProgramContext`; `deriveInitials`/`persona.ts` types→`PersonaDashboardShell`) or `PersonaDashboardShell.tsx` itself, whose consumers (ARC-01/DEV-01/PMD-01/EMD-01) are named explicitly in the PRD but not yet planned — PRD § Scope puts composing-page work, including importing this shell, out of this story's scope.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`. Nearly every one of its 10 concerns is `N/A` for this pure, prop-driven presentational component; § 9 Contract is the substantive section — a bookmark to `docs/requirements/api.md#persona-shell`, which this plan filled with the shell's concrete prop interface (plan-authoring step 10, done in this planning session, not deferred to a task).

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. 12 tasks (T-01..T-12): 7 S, 4 M, 1 L (T-10, the shell's composition + gating logic — the story's single most complex integration point, not split further since it has one cohesive responsibility: turn 3 independently-resolved props into the 3 FR-5 render states). T-01 and T-02 are the two dependency roots (types adapter; tokens.md color tables) with disjoint files — DAG-parallel-safe from the start. No two DAG-independent tasks share a file anywhere in the graph (verified: every `F-NN` appears in exactly one task's `files[]`).

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/SHP-01.md` § Risk Register (numbered 1–11 there; cited here as `R-01`..`R-11` in that same order). Only the 3 HIGH risks are re-cited below per the verification rule (`R-04`, `R-06`, `R-11` are already `closed` in research itself via C-4/C-3/C-4 respectively; the remaining MED/LOW risks inherit their research mitigation unchanged).

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-07 (Integration — identity contract gap: no upstream currently supplies a display name/job title/initials) | HIGH | T-01, T-05, T-10 |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| R-01 (Integration — no frontend session/auth plumbing exists; consuming dashboards could establish divergent session-fetching patterns) | HIGH | accepted — SHP-01 defines the prop shape the shell expects (T-01, `docs/requirements/api.md#persona-shell`) but does not own or build the session-fetch seam itself; no downstream story (ARC-01/DEV-01/PMD-01/EMD-01) is planned yet to claim that ownership. Carried to `pending_carry_forward`. |
| R-02 (Integration — persona-resolver is backend-only; no frontend call site exists, and which story wires `/api/me` or an equivalent is undecided) | HIGH | accepted — same rationale as R-01: SHP-01 defines what the shell does with an already-resolved `persona` value (T-03, T-07, T-10); which story calls AUTH-02's resolver and how is explicitly out of this story's scope (PRD § Scope) and unowned by any planned story today. Carried to `pending_carry_forward`. |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, abbreviated) | Addressed by |
|------|----------------------|--------------|
| C-1  | AUTH-01 `session` contract amendment (decided, not yet done) — plan must not assume the landed contract | T-01, T-10 |
| C-2  | Frontend session context seam — define the exact prop shape the shell expects | T-01 |
| C-3  | Persona enum-to-string mapping — hardcode in `apps/web/src/lib/`, unit-tested, `cio` fails loudly | T-03, T-04 |
| C-4  | EMD subtitle variance — 4 literal subtitles verbatim, no `Title(persona)` template | T-02, T-03 |
| C-5  | CSS binding strategy — shell composes `avatarStyle`/`typeChip`, API/props carry data only | T-06, T-08, T-09 |
| C-6  | Loading/error state UI — define concrete fallback markup, with test coverage | T-07, T-10, T-11 |
| C-7  | Component API clarity — one prop interface, one prop name (`program`), no persona conditionals | T-01, T-10 |

### Cross-Feature Dependency Notes

**No story currently owns the `apps/web` session/persona-fetch seam.** `PersonaDashboardShell.tsx` (F-11) is built, exported, and tested by this story, but nothing in the current codebase imports it — its named consumers, ARC-01/DEV-01/PMD-01/EMD-01, have not reached `/arh-plan-implementation` yet, and per PRD § Scope, fetching/resolving `session`/`persona`/`program` and importing the shell into a real page are explicitly their scope, not SHP-01's. Forcing a `file_plan` entry for a page that does not exist would fabricate scope this story's own PRD excludes (research condition 2; risks R-01/R-02 above). This is the Wiring-dimension exception recorded in § Plan validation below.

Upstream: AUTH-01 (`session` contract, `phase=review`, its own `session`-amendment decided but not yet raised as a change against AUTH-01) and AUTH-02 (`persona-resolver` contract, `phase=security-reviewed`, complete) — both already deliver everything this shell's *interface* depends on; neither blocks this story's own implementation, since the shell is built to handle both the presence and the absence of `signedInUser` by construction (D-01, D-05).

Downstream: the `persona-shell` contract this story fills (`docs/requirements/api.md#persona-shell`) gates `/arh-plan-requirements` for ARC-01/DEV-01/PMD-01/EMD-01 — none of their tasks are in this DAG.

## 7. Test Strategy

| Layer | Test path | TCs covered | Notes |
|-------|-----------|--------------|-------|
| Unit | `apps/web/src/lib/formatPersonaTag.test.ts` | SHP-01-TC-01 | Pure logic — 4 valid personas + `cio` + 1 arbitrary invalid value, all via vitest's already-configured runner |
| Unit | `apps/web/src/components/ProgramContext.test.tsx` | SHP-01-TC-03 | `@testing-library/react` render; asserts a caller-injected `avatarStyle` field is never applied |
| Integration | `apps/web/src/components/PersonaDashboardShell.test.tsx` | SHP-01-TC-02 | `@testing-library/react`; loading suppression, `cio`/raise-sentinel error badge + `aria-live`, identity-bar neutral fallback on undefined `signedInUser` |
| Performance | `apps/web/src/components/PersonaDashboardShell.perf.test.tsx` | SHP-01-TC-04 | Runs inside the **same, already-installed and already-configured vitest runner** (`apps/web/vitest.config.ts`, `package.json` `test` script) via `performance.now()` around 30 render iterations — no new tool, no bench-mode config change; the file matches vitest's existing `src/**/*.test.{ts,tsx}` include glob |

All 4 test cases in `docs/test-cases/SHP-01.json` are covered above. `SHP-01-FR-1` and `SHP-01-FR-3` remain **deliberately uncovered** per that file's own `coverage_audit.uncovered` (an explicit ≤4 test-case cap, both riding the AUTH-01 amendment that has not landed) — this plan does not add a task claiming that coverage; `deriveInitials()` (T-05) and the identity-bar's populated-name render path exist in code but are exercised only once the AUTH-01 amendment lands and that gap is revisited. This is a carried-forward gap, not closed here.

### Coverage gates

- Unit coverage threshold: 80% (fallback default — `harness.yaml` sets no explicit coverage key for the `nextjs` stack).
- No E2E suite exists for this story (`docs/config/project-commands.yaml` `test_e2e: ""`; story Test mapping: "E2E: N/A — covered indirectly by ARC-01/DEV-01/PMD-01/EMD-01 dashboard-compose E2E flows").
- `docs/config/project-commands.yaml` `test`/`test_unit` (`pnpm -C apps/web test`, i.e. `vitest run`) already picks up every new `*.test.{ts,tsx}` file under `src/` with no config change — no new runtime dependency, service, or port is introduced by this story, so `docs/config/project-commands.yaml` and `docs/config/stack-smoke.md` need no edit.

## Plan validation

- Date: 2026-09-03T20:15:00Z
- Verdict: PASS
- Wiring: PASS — every `create` file's consumer is either another file created within this same plan (imported directly at authoring time, e.g. `formatPersonaTag.ts` → `PersonaHeader.tsx`/`PersonaDashboardShell.tsx`) or `PersonaDashboardShell.tsx` itself, whose named consumers (ARC-01/DEV-01/PMD-01/EMD-01) are not yet planned stories — PRD § Scope explicitly places composing-page work, including importing this shell, out of SHP-01's scope (research condition 2). This is a documented cross-story boundary (§ 6 Cross-Feature Dependency Notes), not an inferred-but-missing entry-point: the consumer is named, just not yet built.
- Docs: PASS (no trigger fires) — T1: no new runnable surface (extends the existing `apps/web` app). T2: no new HTTP route. T3: no new env var. T4: no new service/port. PRD § Documentation requirements confirms: "README updates: none... no new route or service." TSDoc requirements (PRD § Documentation requirements) are covered inline in T-01/T-03/T-07/T-08/T-10's task notes, not a separate docs task.
- Runner-setup: PASS — `SHP-01-TC-04` (`type: performance`) runs under vitest, the `nextjs` stack's declared `test_runner` (`harness.yaml`), which is already installed (`apps/web/package.json` devDependencies: `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/dom`) and already configured (`apps/web/vitest.config.ts`: `environment: "jsdom"`, `include: ["src/**/*.test.{ts,tsx}"]`) — confirmed by reading both files directly, not assumed. TC-04 is authored as a plain `*.test.tsx` file using `performance.now()` (per the test case's own precondition, "vitest bench or performance.now()"), which needs no new install and no config change. No `@testing-library/jest-dom` is added either — `@testing-library/react`'s own query methods (`getByText`/`queryByText`, `render`) are sufficient for every assertion in T-04/T-09/T-11, avoiding an unnecessary new dependency.
- Cross-section: PASS — DAG is acyclic (verified: no cycle, every `predecessors` id resolves to a real task). Every declared test-strategy layer (unit, integration, performance) has a matching task (T-04/T-09, T-11, T-12). Every `file_plan` `F-01`..`F-15` is referenced by exactly one task's `files[]`; every task `files[]` id resolves in `file_plan`. No two DAG-independent tasks share a file (verified programmatically over the full task graph — zero conflicts).
- Config drift: PASS (N/A) — no new runtime dependency (`apps/web/package.json` untouched — no `@testing-library/jest-dom`, no bench tool added), no new service, no new port. `docs/config/project-commands.yaml` and `docs/config/stack-smoke.md` need no edit.
- Decision-promotion: PASS — all 5 `DECISIONS.md` entries (D-01..D-05) carry `blast:feature` and `rev:mechanical`; none is `blast:system`/`blast:data` or `rev:effectively-irreversible`, so none requires promotion to a full ADR. All correctly carry `adr:—`.
- Rounds: 1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Continue to hand-off |
