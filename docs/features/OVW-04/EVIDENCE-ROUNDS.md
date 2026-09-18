# Evidence rounds — OVW-04

Round 0 (initial packet, no fix-loop entered): all six dimensions ran; the sole FAIL
(`typecheck`, combined `tsc --noEmit && mypy .`) is TS2559 in
`apps/web/src/app/api/proxy/program-detail/[program_id]/releases/route.test.ts:200` — verified
pre-existing:

- `git diff HEAD -- apps/web/src/app/api/proxy/program-detail/[program_id]/releases/route.test.ts`
  is empty (file unmodified on `feature/OVW-04`).
- `git log -1` on that file resolves to `7d928b76a657330b91631c86f17aaefccf22312c`
  (PGD-06 merge, PR #466) — the failure already exists on `main`.
- Documented as `AF-01` (raised by T-07 during task-mode implementation, before this evidence
  pass ever ran).

No internal fix-loop round was run: the failure traces to a file outside OVW-04's `file_plan`
scope and outside every task's `files[]`. Fixing it here would violate `surgical-changes.md`
(touching a file unrelated to this feature's tasks) and contradicts this session's explicit
instruction not to edit that file. The dimension is reported FAIL with full attribution to
AF-01 rather than silently passed or gamed into N/A — see `docs/features/OVW-04/state.json`
`.impl_evidence.checks.typecheck`.

All other dimensions (unit_tests, lint, runtime, compile) PASS on round 0. `design_check` is
N/A (AF-03) — `design_check:` is empty in `docs/config/project-commands.yaml` by the project's
own documented choice, not an OVW-04 gap.
