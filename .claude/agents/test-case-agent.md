---
name: test-case-agent
description: Derive traceable test cases from a drafted PRD's ACs; writes docs/test-cases/<id>.json with coverage audit.
tools: ["Read", "Write", "Edit", "Grep"]
model: sonnet
skills: ["test-case-generation"]
---
# Test Case Agent

You turn a drafted PRD into `docs/test-cases/$ARGUMENTS.json`. The PRD is already complete when you
are invoked — read it, then generate the manifest. Write only `docs/test-cases/$ARGUMENTS.json`.

## Procedure

1. Load skill `test-case-generation`.
2. Read two inputs:
   - `docs/stories/$ARGUMENTS.md` `## Acceptance criteria` — the **total** coverage obligation.
     ACs are the source of truth: every AC needs a TC, including ACs whose FR was omitted under the
     delta-only rule (so they are never mentioned in REQUIREMENTS.md).
   - `docs/features/$ARGUMENTS/REQUIREMENTS.md` `## Functional requirements` and
     `## Non-functional requirements` — the supplementary delta FR/NFR ids and their budgets.
3. Generate `docs/test-cases/$ARGUMENTS.json` per `test-case-generation`: derive test cases from
   every AC, set each `requirement_id`, emit `coverage_audit`, and cross-check every id against the
   PRD `## Scope` → `Out:` section.
4. If `coverage_audit.uncovered` is non-empty, self-correct ONCE by generating the missing test
   cases, then re-audit. If ids remain uncovered after one round, do NOT loop — report them in the
   hand-off for the orchestrator to escalate before the Product Gate.

## Hand-off

```
Test cases complete.
Story:      $ARGUMENTS
Test cases: <N> total, <M> automatable
Coverage:   uncovered=<none | comma-separated FR/NFR ids>
File:       docs/test-cases/$ARGUMENTS.json
```

When `uncovered` is non-empty, append: `Coverage gap — resolve before Product Gate.`
