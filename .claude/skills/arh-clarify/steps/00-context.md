# Phase 0 — Context

Goal: assemble the inputs Phase 1 needs.

## Procedure

1. Resolve the feature folder: `docs/features/$ARGUMENTS/`. If missing, escalate `feature folder not found`.
2. Collect every `.md` file under that folder (recursive). These are the marker sources for Phase 1.
3. Read `docs/features/$ARGUMENTS/QUESTIONS.md` if present. This is the implementation-agent's session-buffer — a flat list of questions queued during a task. Each line is one question, optionally with `task: T-NN` suffix.
4. Read `docs/features/$ARGUMENTS/state.json`. Pull `.clarifications` (default `[]`). `/arh-clarify` runs post-plan, so the per-feature file always exists; abort with `Per-feature state missing; run /arh-plan-requirements $ARGUMENTS first.` if absent.
5. Compute `next_round = max(round for round in clarifications) + 1` (default `1` when empty).
6. Compute `prior_markers` — the set of marker strings already recorded in any prior round, keyed by exact marker text. Phase 1 uses this to dedupe.

## Output

A context dict for Phase 1:

```
feature_dir:    docs/features/$ARGUMENTS/
md_files:       [list of *.md paths]
questions_md:   QUESTIONS.md content or null
next_round:     <int>
prior_markers:  {set of marker strings}
state_path:     docs/features/$ARGUMENTS/state.json  # per-feature; clarifications[] is P-tier
tracker:        integrations.tracker (from settings)
```

## Validation

If `md_files` is empty AND `questions_md` is null, escalate `nothing to clarify`. The user invoked `/arh-clarify` on a feature with no documents — wrong story id, or `/arh-intake` never ran.
