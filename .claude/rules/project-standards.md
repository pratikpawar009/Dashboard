# Project standards

Their config is the only copy of their standards — read it, never duplicate it into another file.

- Before writing code, check for and read whichever of these exist: `.eslintrc*`, `.prettierrc*`, `ruff.toml` / `pyproject.toml [tool.ruff]`, `tsconfig.json`, `.pre-commit-config.yaml`, `CONTRIBUTING.md`. Follow what they say over generic best practice for the framework.
- Never copy their rules into a Harness-owned file (a skill, a rule, `CLAUDE.md`). A copy goes stale the moment they edit the original — read the source, every time, not a cached summary of it.
- If their config and a generic framework convention disagree on style (not safety), their config wins.
- If no config exists for a concern (e.g. no `.eslintrc` at all), fall back to the framework's own idiomatic defaults, and say so plainly — don't invent a convention and present it as theirs.

## BAD

```
# a Harness rule file, hand-copied once from their .eslintrc:
Use single quotes, no semicolons.
```

## GOOD

```
# rules/project-standards.md points at the source instead of copying it:
Check .eslintrc for their actual quote/semicolon rules before writing JS.
```
