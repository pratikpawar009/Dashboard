# Step 3 — Regression test + evidence

Goal: prove the fix works and lock it so the defect cannot silently return.

## Regression test (mandatory — G4)

Every `/arh-fix` ships a test that would have caught the defect:

- `--from-test` input → that test must now pass; KEEP it (it is already the regression guard).
- Description / tracker input → add a new test reproducing the defect, tagged `regression-FIX-<NN>`. Place it per the project's test convention (`docs/config/project-commands.yaml` test paths).
- The test must FAIL against the pre-fix code and PASS against the fixed code. If it passes both, it does not guard the defect — rewrite it.

A fix without a passing regression test is rejected — return to Step 2.

## Evidence pass (mandatory)

Run the six-dimension evidence pass via the `evidence-pass` skill (the same packet `/arh-implement` uses): `typecheck`, `unit_tests`, `lint`, `runtime`, `compile`, `design_check`. Each PASS / FAIL(≤3 internal fix rounds) / N/A.

- Scope `unit_tests` / `runtime` to what the fix can affect; the FULL suite still runs so the fix did not break a neighbour.
- On any FAIL → the internal fix loop applies (`root-cause-first`, max 3 rounds). Round-3 FAIL → write `docs/fixes/fix-<NN>-ESCALATION.md` and return BLOCKED; do not commit.
- N/A dimensions raise an `evidence-na` note (same mechanism as `/arh-implement`); surface them in the Step 4 record.

## Output

```
Regression test: <id / path> — fails pre-fix, passes post-fix ✓
Evidence: typecheck ✓ · unit ✓ · lint ✓ · runtime <✓|N/A> · compile <✓|N/A> · design <N/A>
Verdict: READY  (or BLOCKED — stop, do not commit)
```
