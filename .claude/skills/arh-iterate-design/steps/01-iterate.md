# Phase 1 — Iterate

Goal: invoke the composer-wired `ux-agent` in **iteration mode** with the baseline DESIGN.md + user feedback. The ux-agent already exists per provider (figma / claude-design / html-mockup / stitch); this step routes inputs into it.

## Procedure

Invoke `ux-agent` with the following context block prepended to its normal prompt:

```
## Iteration context (from /arh-iterate-design)

You are iterating, not drafting from scratch. Read the iteration inputs below and
apply them as a DELTA on top of the baseline DESIGN.md. Do not invent new screens
beyond `REQUIREMENTS.md § Screen inventory`. Do not change the design provider.

- feature_id:   <feature_id>
- round:        <N+1>
- provider:     <integrations.design>
- feedback:     <verbatim text from --feedback, or "(none — full refresh requested)">
- reset:        <yes | no>
- baseline:     docs/features/<feature_id>/DESIGN.history/round-<N>-<iso>.md
                (the previous DESIGN.md; read this BEFORE composing the new one to
                see what was already there; the delta should respect it unless
                --reset was set or the feedback explicitly contradicts a prior choice)
```

The ux-agent's own provider-specific procedure (figma-design / claude-design / html-mockup-design / stitch-design skills) runs normally — its Phase 1–7 (figma) or equivalent. **Iteration mode** modifies only one rule: **prefer minimal frame / file / token changes**. Specifically:

- **figma**: re-discover variables + components (Phases 2–3), but in Phase 5 prefer editing the existing feature page (when present) over creating a new one. Only add frames for screens missing from the baseline; only re-bind tokens that the feedback explicitly calls out.
- **claude-design**: re-ingest `docs/design/<id>/` bundle. The user is expected to have updated exports themselves before invoking; if the bundle is identical to the baseline-time snapshot, surface a note (`bundle unchanged; iteration is a no-op unless feedback was provided`).
- **html-mockup**: regenerate the .html files. Apply feedback as a delta in the HTML template (e.g. "change CTA button to primary color" → token / class change in the affected screens). Per-screen files NOT mentioned in feedback stay byte-identical.
- **stitch**: re-invoke MCP with the feedback as the prompt suffix on `generate_screen_from_text` / `edit_screens`. Variant generation reused for additional form factors.

## Output (replaces baseline)

The ux-agent writes the SAME outputs as a first-pass run:

- `docs/features/<feature_id>/DESIGN.md` — new round content, header includes `**Round:** <N+1>`
- `docs/features/<feature_id>/REQUIREMENTS.md § Visual spec` — one-line pointer (unchanged shape; refreshed `Generated on <iso>`)
- `docs/design/schema.json` — token accumulation if new tokens surfaced
- Provider-specific artefacts (figma feature page id update, html-mockup `screens/*.html` regen, etc.)

## State write (on completion)

```json
{
  "design": "complete",
  "design_iteration": "<the N+1 value from Step 0>",
  "design_artifact": "docs/features/<feature_id>/DESIGN.md",
  "last_updated": "<iso8601>"
}
```

If the ux-agent escalates (`[NEEDS CLARIFICATION]` block in DESIGN.md), set `design = pending` instead of `complete`. The escalation is the user's signal to re-run with better feedback or correct prerequisite gaps (export bundle, Figma file access, etc.).

## Anti-patterns

- Skipping the baseline read — the ux-agent must read the archived prior round in `DESIGN.history/` before composing. Without it, "iteration" is just "redraft" and the delta gets lost.
- Inventing screens not in `REQUIREMENTS.md § Screen inventory` — same rule as a fresh run.
- Changing `design_provider` — that's an `harness add integration design <new>` + full re-generate workflow, not a `/arh-iterate-design` job.
- Decrementing `design_iteration` — counter is monotonic; rolling back means rolling forward (round 5 reverting to round 3's design just becomes round 6 with that content).
