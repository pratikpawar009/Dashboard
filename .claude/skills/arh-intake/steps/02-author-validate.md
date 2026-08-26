# Step 2 — Author + validate (parallel)

Goal: turn every decided RTM row into a validated story file. Authoring and validation
happen in one agent per story, and the stories are independent, so **fan out in parallel**.

## Procedure

For each story row in `docs/requirements/RTM.md`, spawn one `story-author-agent` with the
story id. **Spawn them in parallel** — do not run them one at a time. Each agent:

1. Reads its RTM row (and its `Contract` entry, if any).
2. Writes `docs/stories/<ID>.md` from the effective `story-template`.
3. Validates against `requirement-validation` (floor + template-derived), self-correcting in
   place (cap 3 rounds) for cosmetic failures.
4. Escalates — without looping — if the failure is decompositional (wrong split, missing
   dependency, undefined contract, P1 on a sibling's code).
5. Returns a result payload. It does **not** write `features.json` or edit the RTM.

Collect every payload for Step 3.

## Why parallel is safe here

Each author writes only its own `docs/stories/<ID>.md` — no two touch the same file. The RTM
was written once in Step 1 and is read-only now. The shared-file writes (`features.json`, RTM
`Status`) are deferred to Step 3 and done serially. So there is no write race.

## Escalations

Collect stories returned as `ESCALATED`. These are decomposition defects, not prose
problems — after Step 3, re-run Step 1 once with the reasons, or surface them. Never re-loop
an author on a decompositional failure.

## Edge cases

- A row is too vague even to author → the author escalates it with the reason.
- An existing story file has manual edits since last intake → diff and present the conflict;
  do not overwrite silently.
