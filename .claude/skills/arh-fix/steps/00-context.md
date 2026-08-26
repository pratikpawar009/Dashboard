# Step 0 — Context

Goal: turn the defect input into a concrete, reproducible starting point. No phase preconditions — `/arh-fix` bypasses the SDLC gate — but the loads below are mandatory.

## Parse the input

`$ARGUMENTS` is one of:

- `"<bug description>"` — free text.
- `--from-test <path>` — a failing test. Run it now; capture the failure output verbatim. This IS the reproduction.
- `<TRACKER-KEY>` — a bug ticket. When an issue-tracker provider is configured, fetch the ticket body via the provider integration skill; otherwise abort: `Tracker not configured — pass a description or --from-test instead.`

Extract `--for <feature-id>` if present (used in Step 4 to attach the fix record).

Extract `--debug` if present → **investigate-only mode**: the run stops after Step 1 with an RCA report; Steps 2–4 are skipped. `--debug` is read-only.

## Files to read

1. `CLAUDE.md` — branch naming, commit format, PR conventions.
2. `docs/config/project-commands.yaml` — typecheck / test / lint / build / preflight commands.
3. `.claude/rules/*.md` matching the files likely touched (warm them once the suspect files are known).
4. When `--for <feature-id>` given: `docs/features/<feature-id>/PLAN.md` + DESIGN.md (if present) — so the fix honours the feature's decisions.

## Patterns-skill freshness check (G15)

Run the patterns-freshness check per skill `phase-preconditions` § G15 — warn per unfilled skill (do NOT abort), consequence: "the fix will follow generic conventions".

## Hard preconditions

Stop and surface if:

- Input is empty / unparseable → ask for a description, a `--from-test` path, or a tracker key.
- **(fix mode only — skip when `--debug`)** Current branch is `main` / `master` → create a `fix/fix-<NN>` (or `fix/<slug>`) branch first.
- **(fix mode only — skip when `--debug`)** Working tree has uncommitted unrelated changes → ask the user to commit or stash.

`--debug` is read-only — it never branches, edits, or commits, so the branch and clean-tree guards do not apply; it may run on `main`.

## Assign an id

- **fix mode**: `FIX-<NN>` — zero-padded, next after the highest `FIX-NN` in `docs/fixes/` (default `FIX-01`). Names the branch, commit refs, and `docs/fixes/fix-<NN>.md` record (Step 4).
- **`--debug` mode**: `RCA-<NN>` — next after the highest `RCA-NN` in `docs/fixes/` (default `RCA-01`). Names the `docs/fixes/RCA-<NN>.md` report (Step 1).

## Output

`Context loaded: mode=<fix|debug>, input=<description|test|tracker>, <FIX|RCA>-<NN>, branch=<name|n/a (debug)>, --for=<id|none>. Reproduction: <captured | pending Step 1>. Patterns: <W> unfilled warnings.`
