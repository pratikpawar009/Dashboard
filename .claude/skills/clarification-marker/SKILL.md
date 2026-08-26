---
name: clarification-marker
description: Discipline for [NEEDS CLARIFICATION] markers in stories and PRDs. Forces agents to surface unresolved assumptions instead of guessing.
when_to_use: When drafting a story, PRD, or research doc and an unresolved question would otherwise be silently assumed.
user-invocable: false
allowed-tools: Read Write Edit
---
# Clarification Marker Discipline

Every requirement-phase agent (decomposition, product-spec, story-author) MUST surface unresolved assumptions rather than silently guess. During `/arh-intake` the primary place this happens is the **decomposition step** ([[story-decomposition]]): with the whole requirement in view it asks the user about every shape-changing unknown (no fixed cap at the requirement level — the ≤3 cap below is per *story*), or records a best-judgment Decision — so stories are authored with assumptions already resolved.

## Provenance rule

Every concrete value a story asserts (NFR budget, retry count, WCAG level, status enum,
field schema…) must be one of three — **never a bare invented value**:

| Source of the value | What to write |
|---|---|
| In the RTM row / Decisions block / requirement | use it as-is |
| Source gave none; you chose one | write it **and** log `Decision log`: `<topic>: <value> — assumption, <reason>` |
| High-impact, must not be guessed | leave `[NEEDS CLARIFICATION: <q>]` (cap 3 below) |

A logged assumption and a marker both **pass** validation and surface for the human. A
silently invented specific — no source, no log, no marker — is the failure.

**Scope — spec/behavioral values only.** This rule governs values that, guessed wrong, produce
wrong software: NFR budgets, enums, retry/rounding rules, schemas, behaviours. It does **not**
apply to project-management **metadata** — `Owner` (assigned by a human after intake; leave `—`
if unassigned, never a clarification) or `Updated` (today's date). Never fire a
`[NEEDS CLARIFICATION]` for who owns a story or what today's date is.

A concrete value counts **wherever it appears**, not only in the NFR section. A status code,
enum, threshold, or limit asserted inside an **acceptance-criterion sentence** (e.g. "rejected
with `HTTP 403`", "returns the newest `20` rows") is a spec value the source did not give — it
needs the same provenance (sourced / logged / marked) as an NFR budget. Sourcing the *behaviour*
("non-finance role is rejected", per the requirement) does not source the *specific* the author
chose for it (`403`); log that specific as an assumption too.

## Marker format

Inline:

```
[NEEDS CLARIFICATION: <one-line question>]
```

Examples:

```
- The list pagination uses [NEEDS CLARIFICATION: page size 20 or 50?] items per page.
- Throttle requests at [NEEDS CLARIFICATION: per-user or per-tenant?] level.
- On error, surface a [NEEDS CLARIFICATION: toast or inline banner?] to the user.
```

## Common cases that MUST be marked, not assumed

| Case | Bad (silent assumption) | Good (marker) |
|---|---|---|
| NFR budget unknown | "p95 < 250ms" pulled from thin air | `[NEEDS CLARIFICATION: target p95 latency?]` |
| Persona ambiguous | Pick one of "user" / "admin" arbitrarily | `[NEEDS CLARIFICATION: applies to all roles or admin only?]` |
| Integration point unclear | Assume REST endpoint exists | `[NEEDS CLARIFICATION: does upstream service expose this endpoint?]` |
| Edge case unspecified | Default to "show empty state" | `[NEEDS CLARIFICATION: empty result behaviour — empty state, redirect, or error?]` |
| Auth scope guessed | Assume same as parent feature | `[NEEDS CLARIFICATION: requires auth? same scope as <related>?]` |
| Data retention | Default to "forever" | `[NEEDS CLARIFICATION: retention period for these records?]` |

## Story-template integration

Every story file ends with a "Clarifications" section listing every unresolved marker still in the body:

```markdown
## Clarifications

- [NEEDS CLARIFICATION: page size 20 or 50?]
- [NEEDS CLARIFICATION: applies to all roles or admin only?]
```

Empty section is allowed (and required when zero unresolved markers exist).

## Validation integration

Decomposition resolves the pivotal unknowns up front. At authoring, every remaining concrete
value the source did not give must carry **provenance** ([[requirement-validation]]): sourced,
logged as a `Decision log` assumption, or — for high-impact ones — a `[NEEDS CLARIFICATION]`
marker. A logged assumption and a marker are both **acceptable, non-failing** outputs; the
final summary surfaces them for the human.

The failure the rubric catches is the **opposite**: a plausible invented specific (an NFR
number, a WCAG level, a status enum) presented as if it were a requirement, with no source,
no Decision-log entry, and no marker. Never delete a marker to "look clean", and never emit a
bare invented value — log it or mark it. There is no bounce to another agent: the author adds
provenance in its own context, or escalates.

## Resolving a marker

When the user (or the agent through follow-up questions) supplies an answer:

1. Replace the inline marker with the resolved value.
2. Remove the corresponding line from the Clarifications section.
3. Append to the story's "Decision log" (or PRD "Resolved questions" section):
   ```
   - <YYYY-MM-DD> Page size: 20 (per PO ${person})
   - <YYYY-MM-DD> Scope: admin only (per PRD §2)
   ```

## Hard cap

**Max 3 unresolved markers per artefact** (story, PRD, research doc). Cap forces prioritization: more than 3 ambiguities = story scope is too broad or agent is dumping hard problems on the user. Agent MUST pick the 3 highest-impact questions and either:

- **Resolve the rest inline** with documented best-judgment (record in `## Decision log` with reasoning), OR
- **Escalate** with: `Too many unresolved questions (<N>). Re-scope the story or split into smaller stories.`

Priority order when picking the 3:

1. **Scope ambiguities** (in/out of MVP, persona coverage, phased rollout) — affect what gets built
2. **Security / compliance** ambiguities (auth scope, retention, PII handling) — affect what's safe to ship
3. **Integration boundaries** (API contracts, MCP servers, upstream services) — affect what's possible
4. **UX / behavioural details** (toast vs banner, debounce ms, exact copy) — affect UX but easily revised post-ship

Drop category 4 markers first (resolve inline with best judgment + Decision log entry); promote categories 1-3.

## Anti-patterns

- **Silent guess** — agent picks a value, no marker. Validation rubric will not catch this; only review will. Prefer marker over guess.
- **Vague marker** — `[NEEDS CLARIFICATION: think about this]`. Marker MUST be a specific question with a small set of plausible answers when possible.
- **Marker without question** — `[NEEDS CLARIFICATION]` (no body). Always carry the actual question.
- **Resolving in the wrong place** — editing the inline value but leaving the marker in the Clarifications section, or vice-versa. Both must update together.
- **Bulk-clear before resolution** — agents that delete the Clarifications section to "pass" validation. F-050 lint catches the inconsistency.
- **Marker spam** — emitting 10+ markers in one artefact. Cap is 3 (see "Hard cap" above). Spam = story too broad or agent skipping real decisions.

## Why this skill exists

Without explicit markers:
- LLMs invent plausible-sounding values that look like spec but are unverified guesses.
- Downstream agents (research, plan-implementation) treat invented values as decisions and build on top.
- Bugs surface only at /arh-validate-feature against real users, by which point the cost is high.

With explicit markers:
- Every assumption is flagged at requirement time, when the cost to fix is hours not weeks.
- The Clarifications section is the human's punch list of decisions to make.
- Validation rubric enforces that no story enters /arh-research with unresolved questions.
