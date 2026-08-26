# Step 1 — Decide (decompose → RTM)

Goal: turn `$ARGUMENTS` into the full decided plan in `docs/requirements/RTM.md` — every
story, its dependencies, shared contracts, and priority. This is the only step that reasons
across stories, so it runs **once, in one context**.

## Procedure

Invoke `decomposition-agent` with `$ARGUMENTS`. It:

1. Detects the input type (file / raw text / `JIRA-KEY` / doc URL) and pulls the content.
2. Loads `story-decomposition` and `requirement-tracing`.
3. Decides the complete set of stories as vertical slices — folding false splits (happy
   path / first-time / returning / error of one flow) into acceptance criteria.
4. Assigns `Pri`, `Size`, `Depends-on`, `Contract`; defines every shared interface as a
   `### <name>` section in its per-kind file `docs/requirements/<kind>.md` (the RTM `Contract`
   column points at it). Does not assign a level/wave — build order is derived from `Depends-on`.
5. Records best-judgment Decisions for every shape-changing unknown (no fixed count) and
   returns them as OPEN QUESTIONS.
6. Writes `docs/requirements/RTM.md` (table + Decisions) and each shared interface to its per-kind `docs/requirements/<kind>.md`. No story files.

## Open questions

If the agent returns OPEN QUESTIONS **and a user is available**, ask them with
`AskUserQuestion` — batched, up to 4 per call, as many calls as the list needs — then
re-invoke `decomposition-agent` with the answers so the RTM and its Decisions block reflect
them. Non-interactive run: keep the best-judgment Decisions and carry the questions into the
final summary.

## Edge cases

- Source empty / unparseable → return: `No requirements could be parsed from <source>`.
- Existing RTM (re-run / brownfield) → reconcile; do not duplicate IDs.
- Ticket key not found by the tracker MCP → fail with the explicit MCP error.
