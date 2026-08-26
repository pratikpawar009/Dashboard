---
name: research-assessment
description: Assess a certified story's feasibility — scan strategy, pattern map, risk register, 5-dim scoring rubric with verdict thresholds, and the mandatory state write. Used by research-agent.
user-invocable: false
---
# Research Assessment

The method for turning a certified story into a Feasibility Assessment. Apply these
formats in order; all output appends to `docs/research/$ARGUMENTS.md`.

## Scan

Goal: orient in the parts of the codebase the story touches. Log every command and its result so the assessment is reproducible.

Apply `codebase-exploration` strategy:

1. Top-down: read README, package manifest, top-level layout.
2. Identify candidate modules from the story's user-facing nouns and verbs.
3. Grep before reading. Search for symbols, route paths, schema names.
4. Skim files >300 lines; read files <100 lines fully when relevant.

Append every step to the "Exploration Log" section:

```
## Exploration Log

- `git ls-files src/promo` → 12 files
- `grep -rn "applyPromo" src/` → 3 hits in checkout/, 1 in fixtures/
- Read src/checkout/promo.ts:1-87 — pure validation; no network call
- Open question: how does promo apply at refund time?
```

Hard cap 30 minutes for the scan. If unable to orient in that time, escalate: the codebase is unfamiliar enough to merit human pairing.

## Pattern map

Catalogue what already exists, what to extend, what to create new, and what is at risk of regression.

| Bucket | Definition |
|---|---|
| **Existing code to extend** | Modules whose contract you can add to without changing existing callers. |
| **Existing patterns to follow** | Conventions, helpers, architectural shapes the new code should mirror (don't reinvent). |
| **New files to create** | Concrete file paths the implementation will need (best-guess; refined in plan-implementation). |
| **Shared code at risk** | Modules touched by multiple callers; changes here can ripple. |

Append:

```
## Pattern map

### Existing code to extend
- src/checkout/promo.ts — add `applyMultiplePromos`
- src/api/routes/promos.ts — add `GET /promos/:code/preview`

### Existing patterns to follow
- Repository pattern (see src/db/repos/) — new promo lookup goes here
- API error envelope (see src/api/error.ts) — reuse, don't reinvent

### New files to create
- src/checkout/promoStack.ts
- src/api/routes/promo-preview.ts
- tests/integration/promo-stack.spec.ts

### Shared code at risk
- src/db/migrations/0007_promos.sql — adding a column requires backfill
- src/api/middleware/auth.ts — promo-preview must use the same authn
```

When a pattern decision is ambiguous (extend vs new? which helper to reuse? what naming?), insert `[NEEDS CLARIFICATION: <question>]` per skill `clarification-marker` instead of picking arbitrarily; mirror each into the Clarifications section. Common cases:

- `[NEEDS CLARIFICATION: extend src/api/promo.ts or create src/api/promoStack.ts?]`
- `[NEEDS CLARIFICATION: reuse repository pattern from src/db/repos/order.ts or introduce a query builder?]`
- `[NEEDS CLARIFICATION: shared error envelope or feature-local error type?]`

When the scan reveals a state machine, dependency graph, or layered call path that benefits from a visual, OFFER an inline ASCII diagram in this section. Render only when it materially clarifies; do not auto-generate for trivial flows.

Anti-pattern: do not list everything in the codebase. Map only what the story touches.

## Risk register

Enumerate the risks the implementation will encounter, with severity and mitigation. Append:

```
## Risk register

| # | Dimension       | Severity | Description                                      | Mitigation                                  |
|---|-----------------|----------|--------------------------------------------------|---------------------------------------------|
| 1 | Integration     | HIGH     | Promo service is sometimes-flaky upstream        | Add timeout + retry + circuit breaker       |
| 2 | Compatibility   | MED      | Older clients on app v3.4 do not parse new field | Hide field for clients with `app-version < 4.0` header |
| 3 | Domain          | LOW      | Promo applied after order placed, before capture | Out of scope this story; track separately   |
```

Severity legend:

- **CRITICAL**: ship-blocking. Implementation cannot proceed without resolution.
- **HIGH**: substantial risk to delivery, scope, or correctness. Plan must address.
- **MED**: notable risk, manageable with documented mitigation.
- **LOW**: known issue, accept or defer.

Dimensions to consider: Integration (external services, APIs, MCP servers); Compatibility (older clients, OS versions, browsers); Domain (edge cases, business-rule corners); Performance (budget, scale, contention); Dependency (upstream stories, libraries, vendors); Security (authn/authz, data exposure, supply chain).

Every risk MUST have a mitigation. "Be careful" is not a mitigation. If you cannot confidently rank a risk's severity, insert a `[NEEDS CLARIFICATION: …]` marker and mirror it to Clarifications rather than guessing.

## Score + verdict

5 dimensions, 100 points:

| Dimension       | Weight | Pass criterion                                                              |
|-----------------|--------|-----------------------------------------------------------------------------|
| Integration     | 25     | All upstream dependencies available; failure modes well understood          |
| Compatibility   | 20     | Backward compat plan exists for each affected client/version                |
| Domain          | 20     | Edge cases enumerated; no hidden invariants surfaced during scan            |
| Performance     | 15     | Story has explicit perf budget; estimated work fits within budget           |
| Dependency      | 20     | All upstream stories complete; no blocking external work                    |

Score each dimension 0–100. Total = weighted sum, normalised to 0–100.

| Total | Verdict                | Meaning                                                                  |
|-------|------------------------|--------------------------------------------------------------------------|
| ≥ 80  | **GO**                 | Proceed to /arh-plan-requirements.                                           |
| 70-79 | **GO-WITH-CONDITIONS** | Proceed; PLAN.md must explicitly address the dimensions that scored low. |
| 60-69 | **SPIKE**              | Run a small spike to retire one or more risks before planning.           |
| < 60  | **BLOCK**              | Do not plan; surface the blockers and renegotiate scope or dependencies. |

Any single dimension <40 → automatic SPIKE regardless of total.

Append the Score table, then `**Total: <T>/100 → <VERDICT>**`, then Conditions for GO (when GO-WITH-CONDITIONS), then a Synthesis section:

> 3-5 sentences, readable for a non-Claude human (PO, EM, BA reading the tracker subtask). Lead with the verdict. Cover: what was found, why the score landed there, the single biggest risk, and the next concrete step. Anchor in concrete files + decisions; no vague verbs.

### State write (mandatory, unconditional)

After writing Score + Synthesis, update the state index for `$ARGUMENTS`:

```json
{
  "research": "complete",
  "research_verdict": "<GO|GO-WITH-CONDITIONS|SPIKE|BLOCK>",
  "phase": "research",
  "last_updated": "<iso8601>"
}
```

Runs regardless of `provider`. Status fields MUST be literals — see `docs/state/SCHEMA.md § Field ownership`. The tracker push (`tracker_research`) is the orchestrator's Phase 2, not here. `phase-preconditions` reads `research` to gate `/arh-plan-requirements`; skipping this write breaks the gate.
