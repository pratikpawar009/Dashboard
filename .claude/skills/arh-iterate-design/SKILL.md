---
name: arh-iterate-design
description: Re-invoke ux-agent to refine DESIGN.md for an existing feature without re-running /arh-plan-requirements. `--feedback "<text>"` directs it; `--reset` wipes prior design artefacts first.
argument-hint: "[feature-id] [--feedback \"<text>\"] [--reset]"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash
---
# /arh-iterate-design

Iterate the visual spec for one feature without redrafting the PRD. Use when:

- Designer / PO sees `DESIGN.md` and wants a layout / token / state breakdown change.
- Engineer hit a visual gap during `/arh-implement` and needs the design refined.
- Project upgraded design provider (e.g. html-mockup → figma) and wants to regenerate at the new fidelity.
- New screen added to `REQUIREMENTS.md § Screen inventory` after design first ran; want it covered without re-running `/arh-plan-requirements`.

**Input:** `$ARGUMENTS` (feature id). Parsed positionally from `$ARGUMENTS[0]`. Flags `--feedback "<text>"` and `--reset` are extracted from the remainder.

## Pipeline

```
0. Context + preconditions  (verify state, parse args, archive prior DESIGN.md)
1. Iterate                   (invoke composer-wired ux-agent in iteration mode)
```

## Phase 0 — Context

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-context.md`

## Phase 1 — Iterate

Read and follow: `${CLAUDE_SKILL_DIR}/steps/01-iterate.md`

## State writes

`/arh-iterate-design` increments `.design_iteration` in `docs/features/$ARGUMENTS/state.json` and sets `design = pending` at start, back to `complete` (or `pending` if ux-agent escalates) at end. The `design_provider` field is **not** changed by this command — it always matches `integrations.design` at generate time.

## Hand-off

```
DESIGN.md iterated (round <N+1>).
  Provider:        <integrations.design>
  Feedback:        <verbatim --feedback text | (none — full refresh)>
  Reset:           <yes | no>
  Outcome:         design=<complete | pending>
```

## Anti-patterns

- Running `/arh-iterate-design` to change scope (new screens not in `REQUIREMENTS.md § Screen inventory`) — out of scope; instead update REQUIREMENTS.md and re-run `/arh-plan-requirements`. The ux-agent will refuse to invent screens not in the inventory.
- Running with `integrations.design == none` — aborts; nothing to iterate.
- Using `--reset` on the figma provider hoping to wipe the Figma file — it doesn't; only the local `DESIGN.md` is removed. The shared Figma file stays untouched.
