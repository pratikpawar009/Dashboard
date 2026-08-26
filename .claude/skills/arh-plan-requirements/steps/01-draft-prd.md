# Phase 1 — Draft REQUIREMENTS.md

Goal: produce a PRD that downstream planning depends on. Use `prd-template` for the structure.

## Procedure

Invoke `product-spec-agent` with `$ARGUMENTS` and the resolved `design_mode` from Phase 0.

The agent:

1. Loads `prd-template`, `test-case-generation`, `clarification-marker`.
2. Reads `docs/stories/$ARGUMENTS.md`, `docs/research/$ARGUMENTS.md`.
3. Drafts `docs/features/$ARGUMENTS/REQUIREMENTS.md` per the canonical PRD sections (see `prd-template § Pinned section order`):
   - Problem
   - Outcome
   - Constraints
   - Solution sketch
   - Addressing Research Conditions (when GO-WITH-CONDITIONS)
   - Scope (in / out — both filled)
   - Functional requirements (numbered, observable)
   - Non-functional requirements (concrete budgets, references baseline rules)
   - **Screen inventory** (when `design_mode != none`) — authoritative screen list for the ux-agent
   - **Visual spec** — one-line `ux-agent` pointer; body left as `Pending — ux-agent will write DESIGN.md ...` until handoff completes
   - Rollout plan
   - Documentation requirements
   - Open questions
   - Approvals
4. Stubs `## Visual spec` with the Pending pointer and writes per-feature state at migration (see State write section below): `prd = complete`, `design = pending` (or `n/a` when `design_mode == none`), `design_artifact = "docs/features/$ARGUMENTS/DESIGN.md"`, `design_provider = "{integrations.design}"`.
5. When `design_mode == none`, sets the `## Visual spec` body to `Not applicable — integrations.design = none. Backend / API / data feature.` When `design_mode != none`, leaves the Pending stub; `design` stays `pending`.

The agent does NOT generate test cases and does NOT invoke `ux-agent` — both run next in Phase 2
(`02-parallel.md`): `test-case-agent` writes `docs/test-cases/$ARGUMENTS.json`, and (when
`design_mode != none`) `ux-agent` reads `## Screen inventory`, writes `DESIGN.md`, replaces the
`## Visual spec` stub, and sets `design = complete`.

## Completeness checklist

Before exiting Phase 1, the agent verifies:

- [ ] Every section is filled (no placeholder markers remaining inside Sections 1–3).
- [ ] Scope's "Out:" line is non-empty.
- [ ] Every FR is observable.
- [ ] Every NFR has a number, not an adjective.
- [ ] Open questions list is honest (don't pretend there are none).
- [ ] **No-placeholder check**: zero matches of placeholder phrases in body. See below.
- [ ] **Marker cap**: ≤3 unresolved `[NEEDS CLARIFICATION: ...]` markers (per skill `clarification-marker` Hard cap rule).

If any item fails, the agent self-corrects once. After one failed self-correction, escalate with the specific gaps.

## No-placeholder rule

After drafting, the agent MUST grep its own output for placeholder phrases. ANY match = FAIL the checklist; agent self-corrects with concrete content.

**Forbidden patterns** (case-insensitive):

| Pattern | Why forbidden |
|---|---|
| `TBD`, `TBA`, `to be determined`, `to be announced` | Decision dodged |
| `TODO`, `to do`, `FIXME` | Implementation leakage; PRD is not a backlog |
| `as appropriate`, `as needed`, `as required` | Means "I didn't decide" |
| `add error handling`, `handle errors`, `proper validation` | Vague placeholder for real spec |
| `similar to <X>`, `like <X> but` (without concrete delta) | Refers to undefined precedent |
| `details to follow`, `more details later`, `to be detailed` | Postponed work disguised as commitment |
| `appropriate validation`, `appropriate error message` | "Appropriate" = "I don't know" |
| `lorem ipsum`, `placeholder text` | Fake content |
| `your <X> here`, `<insert X>`, `[X here]` | Template literals leaked |

**Allowed exceptions**:

- `[NEEDS CLARIFICATION: <specific question>]` — explicit ambiguity marker (max 3, per cap above)
- Code blocks containing snippets with `// TODO` from existing referenced source — cite path and line, do not introduce new TODOs
- "Out:" scope items can say "deferred to <next-story>" with an explicit downstream story id

The check is a literal grep: agent runs it after writing each section, NOT only at the end.

```bash
# Example check (agent runs equivalent during drafting)
grep -nEi "TBD|to be determined|TODO|FIXME|as appropriate|as needed|add error handling|similar to|details to follow|lorem ipsum|placeholder text" docs/features/$ARGUMENTS/REQUIREMENTS.md
```

A clean PRD has zero hits. Hits → revise the section with concrete content; if the answer is unknown, replace with a `[NEEDS CLARIFICATION: ...]` marker (subject to the cap).

## State write (mandatory, unconditional) — TWO-TIER MIGRATION POINT

`/arh-plan-requirements` Phase 1 is the **migration point** from index-only state
(`docs/state/features.json[<id>]`) to per-feature state
(`docs/features/<id>/state.json`). After this step, the per-feature file is
canonical for `$ARGUMENTS`; the index entry holds only the status mirror.

### Procedure

1. **Read prior record** from `docs/state/features.json[$ARGUMENTS]` (the pre-plan
   index entry written by `/arh-intake` + `/arh-research`). If absent, error: this command
   ran out of order. The `phase-preconditions` skill should have caught it.

2. **Create per-feature dir** if not present: `mkdir -p docs/features/$ARGUMENTS/`
   (idempotent — `/arh-plan-requirements` Phase 0 may have created it already when
   writing REQUIREMENTS.md draft).

3. **Write `docs/features/$ARGUMENTS/state.json`** with the prior record merged
   with the new PRD fields. Full per-feature record shape per `docs/state/SCHEMA.md`.
   New fields written here:

   ```json
   {
     "prd": "complete",
     "design": "pending | n/a",
     "design_artifact": "docs/features/$ARGUMENTS/DESIGN.md",
     "design_provider": "{integrations.design}",
     "design_iteration": 0,
     "phase": "plan-requirements",
     "needs_clarification_count": <int>,
     "last_updated": "<iso8601>"
   }
   ```

   PLUS all fields copied verbatim from the prior index record (`story`,
   `story_priority`, `story_independent_test`, `research`, `research_verdict`,
   `rtm_source_sha`, `tracker_*`).

4. **Slim the index entry** at `docs/state/features.json[$ARGUMENTS]` to the
   status-mirror shape per `docs/state/SCHEMA.md § Index entry shape`. Drop
   heavy fields (none yet in pre-plan, but `needs_clarification_count` and
   `story_independent_test` move to per-feature). Add status mirrors so the
   index stays useful for cross-feature reads:

   ```json
   {
     "story": "<unchanged>",
     "story_priority": "<unchanged>",
     "research": "<unchanged>",
     "research_verdict": "<unchanged>",
     "prd": "complete",
     "design": "pending | n/a",
     "tracker_story": "<unchanged>",
     "tracker_research": "<unchanged>",
     "rtm_source_sha": "<unchanged>",
     "phase": "plan-requirements",
     "last_updated": "<iso8601>"
   }
   ```

### From this step onward

All subsequent writers for `$ARGUMENTS` target `docs/features/$ARGUMENTS/state.json`
as PRIMARY and mirror selected status fields back to the index per the writer rule
in `docs/state/SCHEMA.md § Writer rule`.

State write runs regardless of `provider`. Status fields MUST be literals — see `docs/state/SCHEMA.md § Field ownership`. Tracker push is Phase 3 (`tracker_prd` only, both locations). `phase-preconditions` reads `gate` to gate `/arh-plan-implementation`; `gate` initialises to `"PENDING"` at Phase 4 entry.
