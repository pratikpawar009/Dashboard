# Step 0.5 — Refresh approved facts

Goal: before any requirement gets parsed, make sure the project's approved knowledge (patterns-skill verified facts, stack info) is still true — cheaply, by replaying what already proved it, not by re-scanning anything.

## Why this runs here, before Step 1

Step 1 fans multiple stories out **in parallel**. If a fact could still change mid-run, sibling stories could read different versions of it depending on timing. Running the refresh once, here, before anything is decomposed, means every parallel sibling reads the same, already-settled context.

## Procedure

1. **Stack facts.** Re-run `harness detect` (no `--write` — this step never edits `harness.yaml` on its own; it only reports). If a declared stack's version now disagrees with what detect finds, that's already `F-057` in `harness validate --strict` — surface it as a one-line warning here too, but do not block on it.
2. **Verified patterns-skill facts.** For every `<!-- BEGIN VERIFIED FACTS -->` block across the project's `<framework>-patterns` skills, run each bullet's own `(see file:line)` proof — treat the citation as the command: confirm the file still exists and the cited line still supports the claim (a changed line number after an edit is not itself a failure; a genuinely different or removed statement is).
   - Still holds → nothing to do.
   - No longer holds → **do not edit the skill file.** Record a one-line drift note instead (see Classify below) and move on. Only the deep-scan approval flow (`/arh-init` Phase 6) may rewrite a verified-facts block.
3. Freeze this refresh's result for the whole intake run — if Step 1 spawns parallel story authors, they all read the same post-refresh context; none of them re-triggers this step.

## Classify a drift note

When a verified fact no longer holds, decide additive vs. corrective the same mechanical way everywhere else in this system decides it:

- **Can you quote the specific bullet it contradicts, verbatim?** Yes → **corrective** — flag it prominently in this step's output; a human should look at it before trusting that pattern again.
- Can't quote it verbatim, or genuinely unsure → **additive/unknown** — log it, queue it for the next deep scan, no gate on this run.

Never treat "I'm not sure" as corrective — an unsure classification that blocks every in-flight feature is the expensive failure mode; queuing it for later is the cheap one.

## Output

```
CONTEXT REFRESH
───────────────
Stack facts:       fresh | 1 stale (see harness validate --strict F-057)
Verified facts checked: <count>
Still holding:      <count>
Drift found:        <count>  (corrective: <n>, additive/unknown: <n>)
```

## Behaviour

- Never re-scan the codebase here — only replay existing citations. A full deep scan is Phase 6 of `/arh-init`, a separate, user-invoked step.
- Never edit a patterns skill's verified-facts block from this step. Flag, don't fix.
- Never block the intake run on drift found here — corrective findings get surfaced prominently, but Step 1 still proceeds.
