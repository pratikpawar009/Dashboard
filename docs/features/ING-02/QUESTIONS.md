# ING-02 — session questions

### Q-01: T-04/T-08 chunk × cols ceiling — safety margin vs hard ceiling
- source: T-04 result payload
- summary: PLAN.md pins `_MAX_ROWS_PER_INSERT = 2_730` (24 × 2,730 = 65,520 < 65,535 psycopg hard ceiling). tasks.json T-08 notes prescribe `× cols ≤ 65_500` (safety margin). These disagree by 20 params.
- orchestrator resolution (2026-09-11): T-08 asserts `chunk_rows × columns < 65_535` — hard ceiling only. PLAN.md pins the constant 2,730 verbatim; a 15-param margin against a hard 65,535 ceiling is not meaningful safety. T-04 ships 2,730 as-is; T-08 tests against the hard ceiling. Q-01 closed.
- status: resolved
