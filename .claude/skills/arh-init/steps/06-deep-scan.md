# Phase 6 — Deep scan (brownfield, mandatory)

Goal: build durable, cited knowledge of how the existing codebase actually works — beyond the config-file facts `harness detect` already found — with a human approving every fact before it becomes something future agents trust.

## When to run

Always, when Phase 0 reported `Mode: brownfield` — there is no choice to offer and nothing to skip. The harness needs real, cited knowledge of the existing codebase before any implementation work starts on it, so this phase runs over the whole repo, every file, no budget cap. Skip entirely for greenfield (nothing exists yet to scan).

Tell the user this is happening — it's a notice, not a question. If any target `<framework>-patterns` skill's `VERIFIED FACTS` block already has content from a prior scan, say so rather than presenting the run as if starting from zero:

```
Running a deep scan of the existing code — mandatory for brownfield projects. This builds
cited, verified knowledge (code patterns, why things are built the way they are) that every
downstream phase relies on before touching this codebase.
<N> facts already verified from a prior scan — refreshing them and looking for anything new.
```

(Drop the last line entirely when there's nothing prior to refresh.)

## Scan (delegate to bootstrap-agent, scan mode)

Invoke `bootstrap-agent` again, in **scan mode**: instruct it to load skill `deep-scan-verification` and run the read → extract → write → purge loop over every folder in the repo (excluding `.git`, `.claude`, dependency directories, build/dist output — see that skill's exclusion list), then **verify every candidate by actually running its proof command** before returning. No file-count or time cap — if a repo is genuinely too large to finish in one pass, the agent stops and reports the remainder as deferred rather than truncating silently. The agent's context is discarded on return — it must not return raw file contents, only:

```
SCAN SUMMARY
────────────
Folders read:      <count>
Candidates found:  <count>
Accepted:          <count>   (proof command confirmed)
Rejected:          <count>   (proof command disagreed — logged with actual output)
Deferred:          <count>   (repo too large to finish in one pass — none if it all finished)

Accepted facts, grouped by destination:
  <framework>-patterns (verified facts section):        [one such group per declared stack]
    - <fact text> (see file:line)
    ...
  <other-framework>-patterns (verified facts section):
    - <fact text> (see file:line)
    ...
  ADR / Flagged gaps:
    - <fact text> (see file:line)
    ...
  Needs a named human sign-off (compliance-sounding):
    - <fact text> (see file:line)
    ...
```

When more than one stack is declared (e.g. a frontend + a backend), each gets its own destination group above — see skill `deep-scan-verification` § "Where verified facts go" for the routing rule.

## Approve (main session, capped at 3 rounds)

Present the accepted facts to the user in **at most 3 rounds**, grouped exactly as the agent grouped them above — never one-at-a-time, never a single dump of everything at once:

1. Round 1 — routine `<framework>-patterns` facts. Batch approve/reject.
2. Round 2 — ADR / architectural facts.
3. Round 3 — anything compliance-sounding. Requires a **named person**, not just "looks right" — record who approved it.

If there are more facts than 3 rounds can reasonably batch, the overflow is **deferred to the next scan** — say so plainly, do not force everything into round 3 and do not silently drop the excess.

## Write (delegate to bootstrap-agent, write mode)

Invoke `bootstrap-agent` again with the approved subset only. It writes:

- Routine facts → the `<framework>-patterns` skill matching the fact's cited file, per skill `deep-scan-verification`'s `paths`-prefix routing rule — its `<!-- BEGIN VERIFIED FACTS -->` / `<!-- END VERIFIED FACTS -->` block only. Never any other part of that file, and never guess a destination when the routing rule is ambiguous (falls back to ADR flagged-gaps instead).
- Architectural facts → an ADR via skill `architecture-decision`'s reverse-engineer branch, or its `## Flagged gaps` section if it is a gap rather than a settled fact.
- Rejected and deferred candidates are **not** written anywhere — they were never approved.

`CLAUDE.md` is never a destination for this phase.

## Output

```
DEEP SCAN COMPLETE
──────────────────
Approved:            <N> facts → <framework>-patterns (per stack), <M> facts → ADRs
Deferred:            <count | none> — re-run the scan later to pick these up
Rejected:            <count> — logged, not written anywhere
```

## Behaviour

- Never write an unapproved fact anywhere. Approval happens in the main session, with a human, every time.
- Never let the scan itself run in the main session — it is delegated so its detail never enters this conversation's context; only counts and the grouped fact list come back.
- Re-running this phase later is always safe — accepted facts refresh by replaying their own proof command, not by re-scanning from scratch (see skill `deep-scan-verification`).
