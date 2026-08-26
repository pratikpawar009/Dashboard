# Phase 0 — Context + design-mode detection

Goal: load the inputs and decide which design provider will produce `DESIGN.md` (figma / claude-design / stitch / html-mockup), or skip the design step entirely when out of scope.

## Preconditions (mandatory)

Load skill `phase-preconditions`. Apply the `/arh-plan-requirements <id>` row:

- `research == "complete"` AND `research_verdict in {"GO", "GO-WITH-CONDITIONS"}` (read from `docs/state/features.json[$ARGUMENTS]` — pre-plan reads the index) — otherwise abort:
  - Missing research → `Run /arh-research $ARGUMENTS first.`
  - Verdict SPIKE/BLOCK → `Research verdict is <X>; address blockers before /arh-plan-requirements.`
- State file present and well-formed.

Do NOT skip this check. Proceed to "Read" only when preconditions return `OK`.

## GO-WITH-CONDITIONS enforcement (mandatory)

When `research_verdict == "GO-WITH-CONDITIONS"` (read from `docs/state/features.json[$ARGUMENTS]`), the research doc carries a `## Conditions for GO` section enumerating concrete blockers that must be addressed in the PRD. These conditions are not optional context — they are part of the contract for advancing.

Procedure:

1. Read `docs/research/$ARGUMENTS.md`. Locate the `## Conditions for GO` section.
2. Extract every numbered condition into a working list (e.g. "1. Add feature flag for app-version compat", "2. Document upstream timeout strategy in PLAN.md").
3. **Inject the list into the PRD scaffold** — `product-spec-agent` MUST add a section to the draft REQUIREMENTS.md titled `## Addressing Research Conditions` containing one bullet per condition with the agent's planned mitigation.
4. Phase 4 (Product Gate) checklist gains an extra check: `[ ] Every condition from research has a concrete mitigation listed`. Gate fails if any condition is unaddressed.

When `research_verdict == "GO"`, the section is omitted (no conditions to address).

Failing this enforcement allows GO-WITH-CONDITIONS to silently degrade into GO and conditions get dropped — the exact failure mode the verdict was designed to prevent.

## Clarifications carry-forward (mandatory)

Read the `## Clarifications` section of `docs/research/$ARGUMENTS.md`. Every still-unresolved `[NEEDS CLARIFICATION: …]` from research MUST appear in the PRD's `## Open questions` section. The product-spec-agent does not silently resolve them — either the user supplies the answer or the marker stays open.

A PRD that drops a research clarification is a regression and fails the Product Gate.

## Read

1. `docs/stories/$ARGUMENTS.md` — must exist and be `Status: Validated`. Otherwise: `Run /arh-validate-story $ARGUMENTS first`.
2. `docs/research/$ARGUMENTS.md` — must exist with `Verdict: GO` or `GO-WITH-CONDITIONS`. Otherwise: `Run /arh-research $ARGUMENTS first`.
3. `CLAUDE.md` — for personas, target platforms, design system pointer.
4. Load skills `prd-template`, `test-case-generation`, `clarification-marker`.

## Detect design mode

`design_mode` mirrors `integrations.design` directly. The role check only determines whether the design step runs at all:

```
if integrations.design == "none":
    design_mode = "none"     # backend / API / data feature; skip design step
else:
    design_mode = integrations.design   # figma | claude-design | stitch | html-mockup
```

For backend-only stories (no frontend / mobile role in scope), `product-spec-agent` MAY override to `design_mode = "none"` even if `integrations.design != none` — but only when REQUIREMENTS.md has no `## Screen inventory` section. Document the override in the PRD's `## Open questions` if uncertain.

## Output

Print one line:

```
Design mode: <figma|claude-design|stitch|html-mockup|none>  (roles=<roles>, design=<integration>)
```
