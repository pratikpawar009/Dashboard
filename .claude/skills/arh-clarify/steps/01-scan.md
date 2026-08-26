# Phase 1 — Scan

Goal: collect every unresolved `[NEEDS CLARIFICATION:` marker across the feature folder.

## Procedure

For each `.md` file in `md_files`:

1. Grep for `[NEEDS CLARIFICATION:`. Record file path, line number, and the marker text (everything between `[NEEDS CLARIFICATION:` and the closing `]`).
2. Skip markers whose text matches a string in `prior_markers` (deduped against earlier rounds).
3. Skip markers that live inside a `## Clarifications` section in `STORY.md` — those are owned by `/arh-intake` and resolved via `clarification-marker`. Mid-stream `/arh-clarify` does not touch them. Detect by: marker is inside `STORY.md` AND the most recent `## ` heading above it is exactly `## Clarifications`.

For each line in `QUESTIONS.md` (when present):

1. Strip whitespace. Skip blank lines and lines starting with `#` (comments / section headers).
2. If the line contains `task: T-NN`, extract it into `blocking`. Otherwise `blocking: null`.
3. Use the remaining text as the marker. Record `source_doc: QUESTIONS.md`, `source_line: <N>`.
4. Dedupe against `prior_markers` and against the inline-marker set already collected.

## Categorization

For each collected marker, pick a category by keyword:

| Keyword in marker | Category |
|---|---|
| `auth`, `scope`, `role`, `tenant`, `permission`, `PII`, `retention`, `encrypt` | `security` |
| `endpoint`, `webhook`, `upstream`, `API`, `contract`, `schema`, `MCP` | `integration` |
| `in scope`, `out of scope`, `MVP`, `phase`, `applies to` | `scope` |
| `toast`, `banner`, `copy`, `debounce`, `tooltip`, `empty state`, `error message` | `ux` |
| (none of the above) | `ux` (default — lowest stakes) |

Categories are best-effort, not gating. The PO sees them as section headers in CLARIFY-<round>.md but can ignore them.

## Surrounding context

For each inline marker, capture the surrounding sentence (`±1 line`). This becomes a small quote block in CLARIFY-<round>.md so the PO sees the marker in situ, not as a disembodied question. `QUESTIONS.md` markers don't have surrounding context — use the marker text only.

## Output

A list of `Question` records:

```jsonc
{
  "qid":         "Q-01",                // assigned in Phase 2, NOT here
  "marker":      "Throttle requests at per-user or per-tenant level?",
  "source_doc":  "docs/features/PAY-1247/PLAN.md",
  "source_line": 42,
  "surrounding": "Apply rate-limiting on POST /payments. [NEEDS CLARIFICATION: per-user or per-tenant?] Default uses bucket size 100.",
  "category":    "security",
  "blocking":    "T-04 | null"
}
```

`qid` assignment is Phase 2's job (it depends on the cap check and the bundle order).

## Cap check

If `len(questions) > 7`, do NOT proceed to Phase 2. Emit:

```
OVERSIZE — re-scope
<N> questions detected. Cap is 7 per round. Common causes:
- Story scope too broad — split into smaller stories.
- Plan-implementation guessed instead of marking. Re-run plan-implementation Phase 1.
- A research dimension was skipped — confirm /arh-research verdict is GO, not SPIKE.
Top 7 by category-priority (security > scope > integration > ux):
  [list first 7]
```

Exit with non-zero status. The user re-scopes, fixes the upstream phase, or re-cuts the story, then re-invokes `/arh-clarify`.
