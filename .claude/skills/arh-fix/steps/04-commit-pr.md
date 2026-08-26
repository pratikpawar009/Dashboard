# Step 4 — Commit + PR

Goal: record the fix, commit behind a human gate, open a PR. Never auto-push.

**Always ask the user before commit/push.** This is the first irreversible step. Auto mode does not bypass this confirmation.

## Write the fix record

Create `docs/fixes/fix-<NN>.md` — the lightweight audit trail (a fix is not a feature, so it lives here, not under `docs/features/`):

```markdown
# FIX-<NN> — <one-line defect>

- Date: <YYYY-MM-DD>
- Input: <description | --from-test <path> | <TRACKER-KEY>>
- Branch: <fix/...>
- For feature: <feature-id | none>

## Root cause
<cause> produces <symptom> because <mechanism>

## Fix
<one paragraph — what changed and why it addresses the cause>

Files: <list>

## Regression test
<id / path> — tag `regression-FIX-<NN>`

## Evidence
typecheck ✓ · unit ✓ · lint ✓ · runtime <✓|N/A> · compile <✓|N/A>
```

When `--for <feature-id>` was given, also append a one-line entry to that feature's per-feature state `docs/features/<feature-id>/state.json` at `.fixes[]`:

```json
{ "fix_id": "FIX-<NN>", "summary": "<one-line>", "regression_test": "<id>", "added_at": "<iso8601>" }
```

`fixes[]` is **P-tier** (per-feature only; no index mirror) per `docs/state/SCHEMA.md`.

## Staging + commit

- Stage ONLY the fix + its regression test. Never `git add -A`. Verify with `git status --short`.
- Commit message — conventional, type `fix`:
  ```
  fix(<scope>): <one-line summary>

  Root cause: <one-line>
  Regression: <test id>
  Refs: FIX-<NN><, feature-id when --for>
  ```

## Push + PR

`git push -u origin <branch>` — never force-push, never push to `main`. Open the PR via the loaded `vcs-<provider>` skill; if none configured, abort: `vcs integration not configured`.

PR body:

```
## Fix
FIX-<NN> — <defect>

## Root cause
<one-line>

## Change
<what + why>

## Regression test
<id> — fails pre-fix, passes post-fix

## Evidence
<six-dimension summary>
```

## Hand-off

`FIX-<NN> committed + PR opened. Awaiting human merge after CI. Record: docs/fixes/fix-<NN>.md.`
