---
name: codebase-exploration
description: Map an unfamiliar codebase efficiently — top-down scanning, grep-before-read strategy, file-size and risk heuristics, Exploration Log format. Used by research-agent.
when_to_use: Before feasibility assessment, impact analysis, or planning a change in unfamiliar code.
user-invocable: false
allowed-tools: Read Grep Glob Bash
model: haiku
---
# Codebase Exploration

A technique for getting oriented in an unfamiliar repository in minutes, not hours.

## Strategy

1. Read top-level layout: `README`, `package.json`/`pyproject.toml`/`go.mod`, `CONTRIBUTING`, `docs/`.
2. Map module boundaries with `Glob '**/index.{ts,js}'` or language-equivalent entry files.
3. Grep before reading. Search for symbols and concepts, then read the most-referenced ones.
4. Skim files >300 lines; read files <100 lines fully when relevant.
5. Capture findings in an Exploration Log as you go.

## Exploration Log format

```
## <Topic / Question>
- **Where**: <file:line refs>
- **What**: <one-line description>
- **Surprises**: <invariants, hidden state, gotchas>
- **Open**: <unanswered questions>
```

## Anti-patterns

- Reading every file in `src/` linearly. Slow and forgettable.
- Asking the user before grepping. Try the obvious search first.
- Treating tests as "too much to read." Test files often document intent better than code.
