---
name: story-template
description: Canonical user story format with Given/When/Then ACs, NFRs, traceability header, dependencies, and test mapping. Sections carry validation hints so the rubric derives its checks from this template.
when_to_use: Drafting or reviewing a user story.
user-invocable: false
allowed-tools: Read Write Edit
---
# Story Template

Sections tagged `<!-- validate: … -->` tell [[requirement-validation]] what to check, so
the rubric tracks this template — customise the template and validation follows. Tags:
`required` (present + non-placeholder), `observable`, `quantified` (a concrete value **with
provenance** — sourced, or logged as an assumption in the Decision log, never a bare invented
number). Sections marked **(floor)** are enforced by Harness regardless of any overlay and
must not be removed.

These `<!-- validate: … -->` comments and the `(floor)` labels are **authoring guidance,
not story content** — strip every one of them from the finished story file. The heading stays;
the annotation on it does not. A `<!-- validate: … -->` or `(floor)` marker left in an authored
story is a leak, not a section.

```
# Story: <ID> — <one-line title>

**Epic**: <EPIC-ID>
**Status**: Draft | In Review | Validated | ESCALATED
**Priority**: P1 | P2 | P3
**Owner**: <name, or — if unassigned>   <!-- metadata: assigned by a human after intake; never a clarification -->
**Updated**: <YYYY-MM-DD>   <!-- metadata: today's date -->


## User story
<!-- validate: required -->        (floor)

As a <persona>, I want <capability> so that <outcome>.

## Acceptance criteria
<!-- validate: required, observable -->        (floor: at least one)

1. Given <state>, when <action>, then <observable result>.
2. Given <state>, when <action>, then <observable result>.

Each AC is referenced downstream by its number as `<STORY-ID>-AC-<n>` — test cases trace to these ids. FRs are delta-only, so ACs are the total traceability anchor. Keep this a flat numbered list; do not group ACs under `### FRn` headers (that namespace collides with FR ids).

## Non-functional requirements
<!-- validate: quantified -->

- Performance: <budget>
- Security: <constraint>
- Accessibility: <wcag-level>
- Observability: <metric|log|trace>

## Dependencies
<!-- validate: required -->

- Upstream: <STORY-ID via CONTRACT, decision, external service, or none>
- Downstream: <stories blocked by this>

## Test mapping

- E2E: <flow file or NA>
- Unit: <module under test>
- Manual: <only when tooling cannot cover>

## Clarifications

<!-- Resolved at decomposition. Empty in a normal story. A residual
     [NEEDS CLARIFICATION: ...] marker is a validation failure — resolve
     from the RTM Decisions block or escalate. See skill clarification-marker. -->

## Decision log

<!-- Append one line per resolved clarification, AND one line per concrete value you chose
     that the requirement source did not give (the provenance rule):
     - <YYYY-MM-DD> <topic>: <resolved value> (per <source>)
     - <YYYY-MM-DD> <topic>: <value> — assumption, <reason>
-->
```

## Field rules

- **Metadata is not spec.** `Owner` and `Updated` are project metadata, exempt from the
  provenance rule ([[clarification-marker]]): `Owner` is `—` until a human assigns it — never
  a `[NEEDS CLARIFICATION]`; `Updated` is today's date. The rule governs spec/behavioral
  values only.
- IDs follow `<EPIC>-<SEQ>` (e.g. `CHK-14`). Split → sibling stories, never `<id>.<n>`.
- ACs are observable. "Code looks clean" is not an AC.
- NFRs are concrete. "Fast" is not an NFR; "p95 < 250ms under 100 RPS" is.

## Priority + independence

- **Priority** — `P1 | P2 | P3`. Required (floor).
  - `P1` — ship-blocker; belongs in the MVP cut.
  - `P2` — important, same release once P1 is in.
  - `P3` — nice-to-have, deferrable.
- **Independence is read from Dependencies**, not a separate flag: a story with no upstream
  dependency is independent; one that depends via a frozen contract is independent once the
  contract lands. A `P1` may depend only via a **contract**, never a sibling story's code —
  the Testability floor and lint F-047 fail otherwise.

## Customising this template

A project overlay may add sections (they will be validated for presence, plus any
`<!-- validate: … -->` tag) or drop non-floor sections (validation stops asking for them).
The **(floor)** sections cannot be removed. See [[requirement-validation]].
