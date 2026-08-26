# Phase 2 — Bundle

Goal: write the PO-facing artefact and the state round.

## Procedure

1. Sort the question list by `(category_priority, source_doc, source_line)` where category priority is `security > scope > integration > ux`.
2. Assign `Q-NN` zero-padded ids in sort order (`Q-01`, `Q-02`, ...).
3. Write `docs/features/$ARGUMENTS/clarify-<next_round>.md` using the template below.
4. Append the round to `docs/features/$ARGUMENTS/state.json` at `.clarifications[]` (preserve all other fields). `clarifications[]` is P-tier; no index mirror.
5. Update `.needs_clarification_count` in the same file to reflect the new total of unanswered questions across all rounds.

## CLARIFY-<round>.md template

```markdown
# Clarifications — Round <N>

- Story: $ARGUMENTS
- Asked at: <YYYY-MM-DD HH:MM UTC>
- Asked by: <phase/step that triggered /arh-clarify>
- Status: asked

Please fill in each `Answer:` field below. When done, the engineer runs `/arh-clarify $ARGUMENTS --apply` to fold answers back into the source docs.

---

## Security (<count>)

### Q-01 · <one-line title taken from the marker>

- Source: `docs/features/$ARGUMENTS/PLAN.md:42`
- Blocking: T-04
- Marker: `[NEEDS CLARIFICATION: <text>]`

> Surrounding context — quoted verbatim from the source doc:
>
> Apply rate-limiting on POST /payments. [NEEDS CLARIFICATION: per-user or per-tenant?] Default uses bucket size 100.

**Answer:**

<!-- PO: fill in below this line -->

---

## Scope (<count>)
...

## Integration (<count>)
...

## UX (<count>)
...
```

Sections with zero questions are omitted entirely (no empty headings).

## State record

The clarifications-round entry written to state:

```jsonc
{
  "round":           <next_round>,
  "asked_at":        "<iso8601>",
  "asked_by":        "<phase/step from QUESTIONS.md header, or 'manual' when user-invoked>",
  "questions": [
    {
      "qid":         "Q-01",
      "marker":      "...",
      "source_doc":  "docs/features/.../PLAN.md",
      "source_line": 42,
      "category":    "security",
      "blocking":    "T-04",
      "answer":      null,
      "answered_at": null,
      "applied_at":  null
    }
  ],
  "tracker_comment": null,
  "status":          "asked"
}
```

`tracker_comment` stays `null` until Phase 3 fills it. `answer`, `answered_at`, `applied_at` stay `null` until `--apply` runs.

## Cleanup

If `QUESTIONS.md` contributed markers to this round, append a `<!-- bundled in CLARIFY-<round>.md -->` footer to it and truncate the bundled lines. Do NOT delete the file — the next session's implementation-agent will re-create it as needed.
