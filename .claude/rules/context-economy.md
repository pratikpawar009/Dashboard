# Context economy

Always-loaded context is re-sent every turn — keep the working set small.

- Don't re-Read a file already read this session; reason from the copy in context.
- After Edit/Write, don't read the file back to "confirm" — the tool errors on failure.
- Large file: Grep to locate, then Read with `offset`/`limit` — never the whole file for one section.
- Delegate read-heavy exploration to a subagent; its context is discarded on return.
