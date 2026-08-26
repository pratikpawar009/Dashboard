# Step 1 — Root cause + architectural bounce

Goal: understand the defect before touching code, and decide whether `/arh-fix` is even the right lane. This step is the gate that keeps `/arh-fix` from becoming a governance backdoor.

## Root cause (mandatory, no fix without it)

Apply the `root-cause-first` skill:

1. Reproduce — confirm the exact trigger (the `--from-test` failure, or steps from the description). Not reproducible → gather more data; do NOT guess.
2. Read the error completely; check recent changes (`git diff`, recent commits, new deps, config drift).
3. State the root cause as one line: `<cause> produces <symptom> because <mechanism>`.
4. For multi-component / deep-stack defects, use the instrumentation + backward-trace techniques in `root-cause-first`.

A fix attempted without a stated root cause is rejected — return to this step.

## Architectural bounce (the guard)

Once the root cause is known, classify it. **STOP and route to `/arh-intake` when ANY of these holds:**

- The fix needs a **new ADR** or contradicts a cited one (an architecture decision).
- It changes a **public contract** — API shape, event schema, DB schema, or a cross-service interface.
- It touches the **data model** / requires a migration.
- It spans **many modules / services** rather than a bounded site.
- It introduces **new behaviour** beyond restoring intended behaviour (that is a feature, not a fix).

Bounce message:

```
This defect is architectural (<which trigger>): <one-line why>.
/arh-fix is the hotfix lane and does not make architecture decisions.
Run: /arh-intake "<reframed as a change request>"  →  it gets research, a PRD, a plan, and the Product Gate.
```

Do NOT proceed to Step 2 on a bounced defect. Stop here.

## `--debug` mode — stop here with an RCA report

When `--debug` was passed, this step is terminal. Do NOT run Steps 2–4 (no fix, no test, no commit). Write `docs/fixes/RCA-<NN>.md`:

```markdown
# RCA-<NN> — <one-line defect>

- Date: <YYYY-MM-DD>
- Input: <description | --from-test <path> | <TRACKER-KEY>>
- Mode: investigate-only (--debug)
- For feature: <feature-id | none>

## Reproduction
<exact trigger / failing test output>

## Root cause
<cause> produces <symptom> because <mechanism>

## Evidence
<what proved it — boundary logs, backward trace, git-diff finding, error excerpt>

## Classification
hotfix-able | architectural (<which trigger>)

## Recommended next
- hotfix-able  → `/arh-fix "<defect>"` (re-run without --debug)
- architectural → `/arh-intake "<reframed change request>"` (gets research, PRD, plan, Product Gate)
```

Then STOP. Report the RCA path + classification to the user.

## Output (fix mode, when not bounced)

```
Root cause:   <cause> produces <symptom> because <mechanism>
Scope:        <files / functions to touch> (bounded)
Regression:   <the test that will be added in Step 3 to lock this>
Classification: hotfix (not architectural) — proceeding to Step 2
```
