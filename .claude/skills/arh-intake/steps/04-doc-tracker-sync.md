# Step 4 — Doc tracker sync

Goal: publish the RTM and (optionally) the validated stories to the configured document tracker so non-Claude readers can see them.

Skipped entirely when `provider: local` in `docs/config/doc-tracker.yaml`.

## Procedure

Read `docs/config/doc-tracker.yaml` to determine provider.

### Confluence

1. Use `mcp__atlassian__createConfluencePage` (or `update*` if the page exists) under `parentPageTitle` in `spaceKey`.
2. Render `docs/requirements/RTM.md` as the page body. Confluence storage format auto-renders fenced markdown tables.
3. For each Validated story, create a child page named `{EPIC}-{SEQ} — {title}` with the story body. Skip Escalated.
4. Capture page URLs into the final summary block.

### Notion

1. Use `mcp__notion__createPage` under `databaseId`.
2. Map RTM rows to database columns. If the database lacks the required schema, ask the user once and write the schema diff to a side note rather than mutating their database.

### Local

No-op.

## Output

```
Doc tracker:
  RTM page:        <url> | local
  Story pages:     <count>
```

## Edge cases

- MCP unavailable → log and continue. The final summary records: `Doc tracker: Skipped (MCP unavailable)`.
- Confluence space exists but `parentPageTitle` does not → create the parent first.
- Conflict on existing page (manual edits) → produce a diff and ask the user before overwriting.
