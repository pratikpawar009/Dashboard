# Evidence packet — ING-05

Six-dimension evidence pass. Rounds: 1 — first-pass clean, no fix-loop invoked. Verdict: **READY**.
Run 2026-09-15 on branch `feature/ING-05` @ `5a5d820`.

| Dimension | Result | Command | Evidence |
|---|---|---|---|
| Typecheck | PASS | `node --check .github/hooks/**/*.mjs` (4 files) | all syntax-clean, exit 0, no output |
| Unit tests | PASS | `node --test .github/hooks/__tests__/` | 23 passed / 0 failed (13 in `copilot-activity.test.mjs` + 10 in `harness-mcp-push.test.mjs`), 41.68s |
| Lint | N/A | (unset) | `docs/config/project-commands.yaml` scopes eslint to `apps/web/**`; `.github/hooks/**` are Node ESM shell-adjacent scripts outside that scope. AF-05 tracks the POSIX-only sub-test as a portability caveat. |
| Runtime | PASS | spawn `harness-mcp-push.mjs` under 2 scenarios | A: `HARNESS_MCP_URL=http://127.0.0.1:1/mcp` → exit 0 in 0.171s, `event=network_error` with `error_code=TypeError`. B: `HARNESS_MCP_URL=http://google.com/mcp` → exit 0 in 0.224s, `event=mcp_url_non_loopback` with `mcp_url_host=google.com`. Both write exactly one allowlisted log line each. |
| Compile | N/A | — | Node ESM — no compilation step. |
| Design check | N/A | — | Backend hook, no UI (design_mode=none, `design=n/a`). |

## Notes

- Logs (`typecheck.log`, `unit-tests.log`, `runtime.log`) are `*.log`-gitignored per repo convention; regenerate locally by re-running the commands above. See [state.json § impl_evidence](../state.json).
- Two setup adjustments during runtime scenario (not source fixes): (1) macOS lacks `timeout(1)` — dropped, the hook self-bounds at `TIMEOUT_MS=10000`; (2) `mktemp -d` lacks a `docs/activity/` subdir, so `writeLog` swallowed ENOENT per AC-5 until the subdir was pre-created. Neither indicates a code defect.
- Unit-test suite is intentionally slower than a JS test framework (~41s) because 3 sub-tests deliberately let the 10 s network stall play out end-to-end to validate `AbortError → event: timeout`. See [`.github/hooks/__tests__/harness-mcp-push.test.mjs`](../../../../.github/hooks/__tests__/harness-mcp-push.test.mjs).
