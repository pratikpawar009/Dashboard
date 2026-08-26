---
name: requirement-validation
description: Story validation — a fixed Harness floor plus checks derived from the project's own story-template (base + overlay), so customising the template never breaks validation.
when_to_use: Validating a story during /arh-intake authoring or /arh-validate-story.
user-invocable: false
allowed-tools: Read Write Edit
---
# Requirement Validation

Validation has two parts. The **floor** is non-negotiable and Harness-owned. Everything
else is **derived from the effective story-template** the project actually uses — so if a
project drops a section (e.g. NFRs) from its `story-template` overlay, validation does not
demand it, and a story is never failed for a section its own template does not declare.

## 1. Floor — always enforced, cannot be removed by an overlay

A story fails validation outright if any of these is missing:

- **ID + user-story sentence** — `<EPIC>-<NN>` and an `As a … I want … so that …` line.
- **≥1 observable acceptance criterion** — externally verifiable. "Code is clean" is not
  observable; "returns 401 on expired token" is.
- **Priority set** — `P1 | P2 | P3`.
- **Independence resolved** — `Depends-on` is present (IDs or `—`). `independent_test` is
  **derived, not asserted**: `true` when `Depends-on` is empty OR **every** id in `Depends-on`
  has a corresponding entry in the `Contract` list (buildable against a stub); `false` as soon
  as **any** dependency is a non-contract dependency on a sibling's *code*. A `false` is
  therefore a decomposition failure — escalate it, do not ship it. A `P1` must be `true`.

The floor is what makes any story a usable input to `/arh-research`, regardless of overlay.

## 2. Template-derived — checks that come from the project's own template

Read the effective `story-template` (base ⊕ overlay). For it:

- **Presence** — every section the template declares must be present and non-empty (not a
  `TODO` / `FILL` / `<…>` placeholder). A section the template does **not** declare is not
  checked.
- **Quality per annotation** — a section may carry a validation hint in the template
  (see [[story-template]]):
  - `quantified` — **scan every number in the section**; each must be concrete (not an
    adjective) AND carry provenance adjacent to it — either sourced, or an `assumption`/`per
    <source>` tag pointing to the Decision log. "fast" fails; a bare `p95 < 250ms` with no tag
    fails; `p95 < 250ms @ 100 RPS — assumption (source gave no budget; per Decision log)`
    passes. One untagged number in the section is a failure — do not eyeball it, check each.
  - `observable` — entries must be externally verifiable (as the floor AC rule).
  A section with no annotation only has to be present and non-placeholder.

### Provenance (floor — applies to every concrete specific)

Enforce the **provenance rule** ([[clarification-marker]]) on every **spec/behavioral** value
the source did not give (NFR budgets, enums, rules, schemas): it must be sourced, logged as a
`Decision log` assumption, or marked. A silently invented value — no source, no log, no marker
— **fails** (cosmetic: the author adds the Decision-log line or a marker). Logging an
assumption does not fail the story; hiding one does. **Metadata is exempt** — an unassigned
`Owner` (`—`) or the `Updated` date is not a provenance violation and must not be marked.

This is why customising the template is safe: the template is the single source of truth
for both a story's structure **and** what gets validated. They cannot drift apart.

## Verdict

- **PASS** — floor holds AND every template-declared section passes presence + its
  annotations.
- **FAIL** — anything else. Self-correct in place (below).

## Self-correction — in the same context, no handback

Authoring and validation run in **one** agent context (see the author step of `/arh-intake`).
When validation fails, classify the failure:

- **Cosmetic** — a fixable wording/completeness gap in *this* story (vague AC, missing
  template section, unquantified budget). Fix it in place and re-check. Cap at 3 rounds.
- **Decompositional** — the defect is in the *decision*, not the prose: wrong split, a
  missing dependency, an undefined contract, a P1 that needs a sibling's code. This cannot
  be fixed by rewriting one story. Mark the story `escalated` and flag it for a single
  re-run of the decomposition step — never loop the author on it.

There is no agent-to-agent handback. A story author cannot summon another agent; it either
fixes in place or escalates the decomposition.

## Unknowns

Big, pivotal unknowns are resolved **before** authoring, at the decomposition step
([[story-decomposition]]) — asked once or recorded as a best-judgment Decision. The many
smaller specifics an author must choose (exact budgets, enums, schemas) are handled by the
Provenance rule above: log each as a Decision-log assumption, or mark the high-impact ones.

A `[NEEDS CLARIFICATION: …]` marker (see [[clarification-marker]]) does **not** fail a story —
it is an explicit open item the final summary surfaces for the human. It must never be
deleted to "look clean." What fails is the opposite: a specific chosen with no source, no
Decision-log entry, and no marker.
