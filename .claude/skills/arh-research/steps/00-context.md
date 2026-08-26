# Phase 0 — Gate (main session)

Goal: confirm the story is ready and its upstreams are sound **before** spending the
research-agent. Read-only. If any check fails, abort here with the helpful message and
do NOT invoke the agent. (Reading the story, loading `codebase-exploration`, and the
pre-flight toolchain check are the agent's job, via skill `research-assessment`.)

## Preconditions (mandatory)

Load skill `phase-preconditions` and apply the `/arh-research <id>` row of its matrix — the row's conditions and abort messages are canonical there; do not re-derive them.

Do NOT skip this check. If the precondition fails, exit immediately with the row's abort message; do not invoke the agent.

## Upstream dependency resolver (mandatory)

Check every story listed in `docs/stories/$ARGUMENTS.md` under `## Dependencies` → `- Upstream:`. Each upstream story id must satisfy ONE of:

| Upstream state | Resolution |
|---|---|
| `state[<dep>].research_verdict in {"GO", "GO-WITH-CONDITIONS"}` | OK, continue |
| `state[<dep>].phase == "implementation"` or later | OK, dep already shipped or being built |
| `state[<dep>]` absent OR `research_verdict in {"SPIKE", "BLOCK"}` | **Abort** with: `Upstream <dep> has verdict=<X>; resolve before researching $ARGUMENTS.` |
| Dependency is external (no story id, e.g. third-party API) | OK, the agent surfaces it as a Pattern/Risk Integration concern |

Why this gate: research builds on top of an upstream's shape. If the upstream is BLOCK or unknown, the pattern-map and feasibility score is built on assumptions that may evaporate when the upstream is re-scoped. Refuse early; cost of resolution is hours, not weeks.

Output of this check:

```
Upstream dependencies (<count>):
  ✓ AUT-02     research_verdict=GO        OK
  ✓ API-01     phase=implementation       OK (already shipping)
  ⨯ DSH-01     research_verdict=SPIKE     BLOCKED — resolve first
```

Any `⨯` = abort. Do not invoke the agent.

## Patterns-skill freshness check (G15)

Run the patterns-freshness check per skill `phase-preconditions` § G15 — warn per unfilled skill (do NOT abort), consequence: "research pattern-map will be generic".

## Output

`Gate passed for $ARGUMENTS. Story status=Validated, <N> upstreams OK, <W> unfilled-patterns warnings. Invoking research-agent.`
