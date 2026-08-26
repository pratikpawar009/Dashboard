# Phase 3 — Tracker comment

Goal: post one batched tracker comment per round so the PO sees the questions in their normal tool, not just in the repo.

## Procedure

1. If `integrations.tracker == none`, skip this phase entirely. The CLARIFY-<round>.md artefact in the repo is sufficient. Do NOT escalate.
2. Otherwise, build the comment body using the template below.
3. Post the comment against `tracker_story` (read from `docs/features/$ARGUMENTS/state.json`). If `tracker_story` is null (intake never pushed), escalate `cannot post clarification — no tracker story key for $ARGUMENTS. Run /arh-sync first or invoke /arh-clarify after /arh-intake has pushed`.
4. Record the comment id in `.clarifications[<round>].tracker_comment` in `docs/features/$ARGUMENTS/state.json`.

## Comment body template

```markdown
**Clarifications — Round <N>** ({count} questions; bundled by /arh-clarify)

Repo artefact: `docs/features/$ARGUMENTS/clarify-<N>.md` (fill in `Answer:` fields and reply here when done; engineer runs `/arh-clarify $ARGUMENTS --apply` to fold answers back into the spec).

### Security
- **Q-01** — Throttle requests at per-user or per-tenant? · blocks T-04 · `PLAN.md:42`
- **Q-02** — ...

### Scope
- **Q-03** — ...

### Integration
- **Q-04** — ...

### UX
- **Q-05** — ...

(Re-asking is wasteful; please put all answers in one reply.)
```

Section headings with zero questions are omitted.

## Rate-limit awareness

If the tracker provider rate-limits comments and a recent round was posted < 5 minutes ago (check `prior round.asked_at`), warn the user before posting:

```
warning: prior CLARIFY round posted <N>min ago. The PO probably hasn't seen it yet.
Proceed? [y/N]
```

This is a workflow guardrail, not a hard block — sometimes you genuinely have new questions.

## Failure handling

If the comment post fails (auth expired, tracker down):

1. State is still written from Phase 2. The repo artefact is still on disk.
2. `tracker_comment` stays `null`. `.clarifications[<round>].status` in `docs/features/$ARGUMENTS/state.json` stays `asked`.
3. Emit: `tracker post failed — round recorded locally. Retry with /arh-clarify $ARGUMENTS --resync after restoring tracker auth.` (`--resync` is reserved for v2; for now the user re-runs the bare `/arh-clarify` to retry — Phase 0 will pick up the round with `tracker_comment: null` and Phase 3 will retry.)
