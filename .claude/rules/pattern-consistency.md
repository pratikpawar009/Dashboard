# Pattern consistency

Old code and new code get different rules — knowing which one applies is what keeps a codebase from getting more inconsistent over time, not less.

## Editing an existing file

Always match that file's own style, even if the rest of the codebase does it differently, and even if you would write it differently yourself. This applies **no matter how consistent or inconsistent the wider codebase is** — a single bug fix does not get to also "improve" the file's conventions. See `.claude/rules/surgical-changes.md` for the same discipline applied to scope more broadly.

## Writing a new file

- **A dominant pattern exists** (most of the codebase agrees on how to do this kind of thing) → follow the dominant pattern, even over generic framework best practice. Consistency with this codebase wins over an abstractly "better" convention.
- **Nothing like this exists yet anywhere in the codebase** → fall back to the framework's real, well-known best practice, and say so plainly rather than presenting it as this team's convention.
- **The codebase is genuinely split, no dominant pattern** → do not guess and do not silently pick one. Escalate once, let a human decide, then record the decision (e.g. via skill `decide`) so every future new file follows it automatically without asking again.

## What never changes because a new decision was made

Deciding a new convention for future code does not retroactively apply to old files. Old files only change when someone is already touching that specific file for another reason, or the team explicitly starts a dedicated cleanup — never as a side effect of "we picked a standard."

## BAD

```
# Fixing a typo in order.py, which uses callbacks — "while I'm here" it gets
# rewritten to async/await because that's the pattern in newer files.
```

## GOOD

```
# Fixing a typo in order.py — stays on callbacks, matching the rest of that
# file. The async/await convention only applies to new files from here on.
```
