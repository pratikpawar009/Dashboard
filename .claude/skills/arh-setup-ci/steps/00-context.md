# Phase 0 — Context

Goal: read enough to compose the pipeline correctly.

## Read

1. `docs/adr/0001-tech-stack.md` § Decision — CI provider (Integrations.ci) and Frameworks list. If the ADR is missing, run `/arh-init` first.
2. `docs/config/project-commands.yaml` — typecheck/test/lint/build commands per stack.
3. `CLAUDE.md` — for project-wide CI rules (e.g. block on lint errors).
4. Stack-overlay recipes: each `stacks/<name>/fragments/cicd-recipe.yaml` (when present).

## Output

```
CI provider: <name>
Stacks:      <list>
Recipes:     <count> stack recipes loaded; <missing> stacks have no recipe (placeholder jobs only)
```
