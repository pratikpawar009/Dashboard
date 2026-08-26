---
name: adr-template
description: Architecture Decision Record template (Status / Context / Decision / Consequences) and an ADR index pattern.
when_to_use: Capturing a non-trivial design decision in docs/adr/.
user-invocable: false
allowed-tools: Read Write Edit
---
# ADR Template

```
# ADR-<NNNN>: <one-line title>

- Status: Proposed | Accepted | Superseded by ADR-<MMMM> | Deprecated
- Date: <YYYY-MM-DD>
- Deciders: <names>

## Context

What problem are we solving? What forces are at play (tech, organisational, time)?

## Decision

The chosen approach in one paragraph. State it as a decision, not a discussion.

## Consequences

- Positive: …
- Negative: …
- Reversible? Cost to undo if wrong.
```

## Index pattern

`docs/adr/README.md` lists every ADR with id, title, status. Update on every new ADR.
