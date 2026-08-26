---
name: prd-template
description: PRD template and completeness checklist for the Product Gate. Use to draft REQUIREMENTS.md from a certified story plus research assessment.
when_to_use: Drafting or auditing a PRD stub during /arh-plan-requirements.
user-invocable: false
allowed-tools: Read Write Edit
---
# PRD Template

## Pinned section order (mandatory, exact spelling and case)

The PRD body MUST emit these top-level sections in this exact order. No extra `## `-level sections. Sub-sections (`### `) may appear inside as documented per section.

1. `## Problem`
2. `## Outcome`
3. `## Constraints`
4. `## Solution sketch`
5. `## Addressing Research Conditions`  *(emit only when `research_verdict == "GO-WITH-CONDITIONS"` in `docs/state/features.json[<id>]` — pre-plan read; omit entirely otherwise)*
6. `## Scope`
7. `## Functional requirements`
8. `## Non-functional requirements`
9. `## Screen inventory`  *(emit when `integrations.design != none`; omit for backend-only features)*
10. `## Visual spec`  *(emit when `integrations.design != none`; body is a one-line `ux-agent` pointer to `DESIGN.md` — never inline wireframes / token tables; omit when `integrations.design == none`)*
11. `## Rollout plan`
12. `## Documentation requirements`
13. `## Open questions`
14. `## Approvals`

There is NO `## Resolved questions` section. Resolved decisions live in `docs/stories/<id>.md` § Decision log (canonical source). The PRD's `## Open questions` ends with a single line: `Decisions logged in docs/stories/<id>.md § Decision log.`

The lint rule **F-051** (warn) fires on any PRD whose `## ` section set deviates from this list.

## Body template

```
# Feature: <id> — <title>

## Problem
What is broken or missing? Who feels it?

## Outcome
The observable change in user or system state when this ships.

## Constraints
Hard constraints (legal, perf budget, deadlines, dependencies).

## Solution sketch
One paragraph; no implementation detail.

## Addressing Research Conditions
<!-- Only when research_verdict == "GO-WITH-CONDITIONS". One bullet per numbered
     condition from docs/research/<id>.md § Conditions for GO, with concrete
     mitigation. The Product Gate fails if any condition is unaddressed. -->
- C-1: <condition verbatim> — <mitigation in this PRD>

## Scope
- In: …
- Out: …

## Functional requirements

<!-- FR rule (mandatory):
     Emit `**<STORY-ID>-FR-N**` ONLY when the FR adds implementation-level
     constraints beyond the story AC (specifics: algorithms, header parsing,
     side-effect ordering, error codes, normalisation rules, etc.).
     When the FR would verbatim restate the AC, OMIT it.
     Do NOT add `### ` subsection headers inside this section (e.g.
     `### FR1 — <group>` copied from the story's AC groupings): they collide
     with the `<STORY-ID>-FR-N` id namespace and leak into test-case
     requirement_ids. This section is the trace header + `**<STORY-ID>-FR-N**`
     delta blocks only.
     Always emit this header line first: -->

FRs trace 1:1 to story ACs; see `docs/stories/<id>.md` for canonical wording.
New impl constraints introduced below (when any):

**<STORY-ID>-FR-N** — <short title>  *(extends AC #M with: <one-line summary>)*

<body — only the new constraints, not a paraphrase of the AC>

## Non-functional requirements

<!-- NFR rule (mandatory):
     Each bullet starts with ONE of:
     (a) `Per `.claude/rules/<rule-name>.md`:` plus a one-line scope statement —
         when the constraint is cross-cutting baseline content (a11y AA, secret
         scan, no-PII-in-logs, ownership 404 not 403, prefers-reduced-motion,
         touch target ≥ 44x44 dp, WCAG 2.2 AA modal, etc.). The rule body is
         the canonical text; do NOT re-paste its bullets here.
     (b) A feature-specific numeric budget or threshold —
         e.g. `PATCH p95 < 150 ms at 50 RPS sustained for 60 s`.
     Never inline rule-baseline bullets verbatim. -->

- Performance: …
- Security: Per `.claude/rules/security-baseline.md`: applies to all new endpoints in scope. <feature-specific additions only>
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to all new UI surfaces. <feature-specific additions only>
- Observability: …

## Screen inventory
<!-- Authoritative list of screens this feature introduces or modifies. The
     ux-agent reads this section to compose hi-fi designs per provider; never
     invents screens. One row per screen. `Route` is the URL path the screen is
     served at (— for a modal / embedded partial with no own route). `Render` is
     server | client | static | live (live = server-push / streamed: LiveView,
     Turbo/Hotwire, WebSocket, SSE); append a parenthetical note for finer modes
     (e.g. "server (ISR 60s)", "static+islands", "client (mobile screen)"). Omit
     this section entirely when `integrations.design == none` (backend / API /
     data feature). -->

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| <Screen name> | <e.g. /checkout, /orders/:id, —> | server \| client \| static \| live <note> | <one-line> | Populated / Loading / Empty / Error | <AC #1, AC #3> |

## Visual spec
<!-- One-line pointer. The ux-agent for the configured design provider
     (figma / claude-design / stitch / html-mockup) writes the full visual
     spec to DESIGN.md and replaces this body with the final link. Do NOT
     inline wireframes / screen tables / token tables here. -->

Pending — `ux-agent` will write [DESIGN.md](./DESIGN.md) during `/arh-plan-requirements` design phase.

## Rollout plan
- **Strategy**: pilot | phased | bang-bang
- **Feature flag**: <flag name | none>
- **Backout plan**: <how to disable without deploy>
- **Success signal**: <metric + threshold that gates next phase>

## Documentation requirements
<!-- REQUIRED for any feature that introduces a new runnable surface (server, frontend
     app, CLI binary). /arh-plan-implementation lifts each line into a tracked task. -->
- **README updates**: <file path + what it must cover>
- **Runbook**: <file path | none>
- **API reference**: <openapi/swagger location | none>
- **Inline code comments**: <areas that need NatSpec/JSDoc/docstring | none>
- **Examples / how-to**: <docs/<feature>.md path | none>

When this section is empty for a story that introduces a runnable surface, the
`plan-validation` rubric's Docs dimension will fail.

## Open questions
<!-- Mirror every [NEEDS CLARIFICATION: ...] marker still in the body. Empty when none. -->
- …

Decisions logged in `docs/stories/<id>.md` § Decision log.

## Approvals
- **<YYYY-MM-DD>** — <Approver name> (PO + Designer + BA, single-approver mode covers all when one human): **APPROVE | CHANGES**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs reviewed in `DESIGN.md` (when `integrations.design != none`); N/A for backend-only features
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=<N>
  - Research verdict <GO|GO-WITH-CONDITIONS> (all conditions addressed when applicable)
  - Tracker subtask: <KEY-XX>
```

## Completeness checklist (Product Gate)

- [ ] Problem describes a real user or operational pain
- [ ] Outcome is measurable
- [ ] Scope is explicit ("Out:" is filled, not blank)
- [ ] **Section set matches the pinned list above** (no extra, no missing, no renames) — F-051 silent
- [ ] FR section opens with the trace-map header; FRs enumerated ONLY when they add info beyond AC
- [ ] NFR bullets reference rule files OR cite feature-specific numeric budgets — no inlined baseline copy
- [ ] Documentation requirements section is filled (or explicitly empty with rationale when no runnable surface introduced)
- [ ] **Rollout plan present** — strategy + feature flag + backout
- [ ] No open questions block implementation (Open questions section is empty OR every entry is annotated as non-blocking)
- [ ] All `[NEEDS CLARIFICATION]` markers from upstream story have been resolved (see story Decision log)
- [ ] Approvals section recorded with date + name + APPROVE literal

## Rollout strategy reference

Every PRD MUST declare how the change ships. Three strategies:

| Strategy | Use when | Example |
|---|---|---|
| **pilot** | High blast-radius change; need a small cohort to validate before broad rollout | Migrate auth flow; pilot with 1% internal employees first |
| **phased** | Material UX or perf change; staged % rollout with metric gates | New checkout flow; 5% → 25% → 100% gated by p95 latency |
| **bang-bang** | Low blast-radius; backwards-compatible; trivial to revert | Add a new optional API field; deploy everywhere at once |

A feature flag is REQUIRED for `pilot` and `phased`. A backout plan is REQUIRED for all three (even bang-bang — there must be a way to revert without redeploying).
