# ING-01 — Agent flags

All flags raised this session have been triaged. Verdicts, rationales, and the audit trail
(`decided_by` / `decided_at`) live in `docs/features/ING-01/state.json` → `.agent_flags[]`.
The two deferred flags are linked to rows in `.pending_carry_forward[]`.

| Flag | Kind | Verdict | Summary |
|---|---|---|---|
| AF-01 | observation | **defer** → `AF-01-dev-db-default-writes-real-db` | live Postgres on the `Settings.database_url` default means an unset `DATABASE_URL` writes to the real dev DB |
| AF-02 | observation | **reject** (kept as built) | per-reason 401 `detail` diverges from `auth.py`'s generic `invalid_token`; load-bearing for TC-21 |
| AF-03 | env-blocker | **defer** → `AF-03-pnpm-ignored-builds-gate` | `ERR_PNPM_IGNORED_BUILDS` on `unrs-resolver@1.12.2` breaks every composite command's frontend half |
| AF-04 | evidence-na | **accept** (N/A confirmed) | `design_check` N/A — no tool wired, and `design: n/a` with no UI surface |

<!-- triaged 2026-09-03 by pawar.pratik0903@gmail.com -->
