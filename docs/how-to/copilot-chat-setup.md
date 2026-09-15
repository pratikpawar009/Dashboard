# Copilot Chat activity → dashboard bridge

VS Code Copilot Chat slash-command sessions flow into the same activity pipeline as Claude Code. On `sessionEnd`/`Stop`, [`.github/hooks/copilot-activity.mjs`](../../.github/hooks/copilot-activity.mjs) reads the local Copilot Chat journals, upserts one record into `docs/activity/activity.jsonl` keyed by `(session_id, cmd_ts)`, then spawns [`.github/hooks/harness-mcp-push.mjs`](../../.github/hooks/harness-mcp-push.mjs) detached to POST the row to the local MCP server (fire-and-forget, single 10 s attempt, no retry). The row lands in `usage_events` via ING-04's `push_activity` tool → ING-02's `POST /api/ingest/activity`.

## 1. Prerequisites

- **VS Code** with the **GitHub Copilot Chat** extension enabled.
- **Node 20+** on `PATH` (the hooks use `node:test` and Node's built-in `fetch`).
- **`services/mcp-server/` running locally** — FastMCP streamable HTTP on `127.0.0.1:3010`, path `/mcp`. Boot per [`services/mcp-server/README.md § Run`](../../services/mcp-server/README.md).
- **`AGENTRISE_INGEST_TOKEN`** set in the MCP server's env (ING-04 owns token custody; see [`services/mcp-server/README.md § Environment variables`](../../services/mcp-server/README.md)). The Copilot Chat hook **never reads a token** and **never talks to anything but loopback**.
- **`.harness/program.yaml`** at the workspace root with a top-level `program_id` (or set `HARNESS_PROGRAM_ID` — see § 4).

## 2. Wire the hook into VS Code Copilot Chat

The hook wiring lives in [`.github/hooks/hooks.json`](../../.github/hooks/hooks.json) — the harness convention already registers both `sessionEnd` and `Stop` to invoke `copilot-activity.mjs`. No per-machine VS Code `settings.json` edit is required; Copilot Chat's session-end event fires the hook via that config.

```json
{
  "version": 1,
  "hooks": {
    "sessionEnd": [{ "type": "command", "bash": "node .github/hooks/copilot-activity.mjs", "timeoutSec": 15 }],
    "Stop":       [{ "type": "command", "bash": "node .github/hooks/copilot-activity.mjs", "timeoutSec": 15 }]
  }
}
```

The 15 s `timeoutSec` is the outer VS Code budget; the hook itself returns in **< 2 s p95** because the MCP push is spawned detached (`{detached: true, stdio: 'ignore'}` + `.unref()`) and the parent hook exits immediately after the NDJSON write.

## 3. Environment variables

| Var | Default | Required | Notes |
|---|---|---|---|
| `HARNESS_PROGRAM_ID` | — | one of this OR `.harness/program.yaml` | Env wins over YAML. See [ADR-0015](../adr/0015-program-id-sourcing-precedence.md) for the four-step precedence: env → `program.yaml program_id` → legacy `programId` → skip. |
| `HARNESS_MCP_URL` | `http://127.0.0.1:3010/mcp` | no | MUST be IPv4 loopback (`127.0.0.1` or `::1`). A non-loopback host is refused with `mcp_url_non_loopback` and the push exits 0 without sending (NFR-Security). Deliberately not `localhost` — Windows resolves that IPv6-first and the MCP server binds IPv4, so `localhost` silently times out. |
| `HARNESS_WORKSPACE_ROOT` | two levels above the hook script (`.github/hooks/../..`) | no | Only override when the hook runs from a non-standard location. |
| `HARNESS_INGEST_TOKEN` | — | **DO NOT SET on the hook side** | Bearer custody lives on the MCP server (`AGENTRISE_INGEST_TOKEN`). The hook talks only to loopback; a token on the hook side is dead weight and a leak surface. |

## 4. What gets recorded

Each `sessionEnd` upserts one row into `docs/activity/activity.jsonl` matching `services/api/app/schemas/ingest_files.py::ActivityRowIn`:

- **Populated per-command**: `program_id` (per ADR-0015), `session_id`, `cmd_ts`, `command`, `user`, `duration_seconds`, `outcome`, `total`, `input_tokens`, `output_tokens`, `models`, `copilot_credits`.
- **`feature`** — parsed via `^/\S+\s+([A-Z]{2,4}-\d+)\b` (bare-token positional immediately after the slash-command name). `/plan BED-01` → `"BED-01"`; `/plan --feature BED-01` → `null`; `/plan` → `null`.
- **`source`** — literal `"copilot"` (distinguishes from Claude Code rows written by [`.claude/hooks/harness-activity.mjs`](../../.claude/hooks/harness-activity.mjs)).
- **Known-zero fields** (documented limitations, as of 2026-09-15):
  - `cache_read = 0` and `cache_write = 0` — Copilot Chat's journal does not split cache-hit vs cache-write tokens; the literal `0` means "measured and known zero", distinct from `null` = "not measured".
  - `lines_added = 0` — the journal records tool call filepaths, not diff volume. `files_created` and `files_modified` are counted; line volume is not.

## Verify

Run this once after setup to confirm the wiring is live. Order matters — each step gates the next.

1. **MCP server responds on loopback**:
   ```bash
   curl -sfo /dev/null -w '%{http_code}\n' http://127.0.0.1:3010/mcp
   ```
   Non-2xx or connect-refused → boot `services/mcp-server/` per its README before continuing.
2. **`program_id` resolves**:
   ```bash
   node -e 'const fs=require("fs"),p=".harness/program.yaml";console.log(process.env.HARNESS_PROGRAM_ID?.trim()||(fs.existsSync(p)?(fs.readFileSync(p,"utf8").match(/^\s*(?:program_id|programId)\s*:\s*(.+?)\s*$/m)?.[1]):null)||"UNRESOLVED")'
   ```
   Prints your program id. `UNRESOLVED` → fix env or `.harness/program.yaml` per § 3.
3. **Hook syntax-checks**:
   ```bash
   node --check .github/hooks/copilot-activity.mjs && node --check .github/hooks/harness-mcp-push.mjs
   ```
   Exits 0 silent = OK.
4. **Hook unit tests pass**:
   ```bash
   node --test .github/hooks/__tests__/
   ```
   Expected: `# pass 23 # fail 0`.
5. **Live smoke** — trigger any slash-command in Copilot Chat (e.g. `/plan ING-05`), wait for the session to end, then:
   ```bash
   tail -n 1 docs/activity/activity.jsonl | jq '{session_id, cmd_ts, source, feature, program_id, outcome}'
   tail -n 1 docs/activity/.mcp-push.log
   ```
   `activity.jsonl` should show `source:"copilot"` with the resolved `program_id` and (for `/plan ING-05`) `feature:"ING-05"`. `.mcp-push.log` should show `{"event":"success",...}` within ~2 s of the session ending.

Any step failing before step 5 means the hook will refuse to write (per NFR-Security / ADR-0015). Any failure at step 5 → jump to § 5 Troubleshooting.

## Manual E2E walkthrough

Full lifecycle check — run this after each material Copilot Chat / VS Code / hook upgrade, and once when first wiring a new workspace. Not automated; there is no CI for this feature (`docs/config/project-commands.yaml` → `CI: none`).

1. **Baseline the log**:
   ```bash
   wc -l docs/activity/activity.jsonl docs/activity/.mcp-push.log
   ```
   Note the two line counts as `L0`.
2. **Run one recognisable slash-command** in Copilot Chat:
   - Type `/plan ING-05` (or any feature id).
   - Let it complete and end the session (close the chat or run another slash-command to close the prior turn).
3. **Verify the row landed** — within ~2 s of `sessionEnd`:
   ```bash
   wc -l docs/activity/activity.jsonl docs/activity/.mcp-push.log
   # both counts should be L0 + 1
   ```
   ```bash
   tail -n 1 docs/activity/activity.jsonl | jq
   ```
   Expected: matches `ActivityRowIn` — `source:"copilot"`, `feature:"ING-05"`, `program_id:"<yours>"`, `command` starting with `/plan`, `outcome:"success"` (or `"error"` if the command failed — either is a successful hook run), non-null `session_id` and `cmd_ts`, `duration_seconds ≥ 0`, `total ≥ 1`, `cache_read = 0`, `cache_write = 0`.
   ```bash
   tail -n 1 docs/activity/.mcp-push.log | jq
   ```
   Expected: `{"event":"success", "ts":"…", "http_status":200, "duration_ms":<n>, "mcp_url_host":"127.0.0.1"}`. No `program_id`, `user`, command text, or bearer token in the log line (allowlist per § 5).
4. **Confirm dashboard visibility** — open the CIO Portfolio (or any persona) dashboard and confirm the row surfaces under the resolved `program_id`. Ingest tier is ING-02's `POST /api/ingest/activity` via ING-04's `push_activity` tool; dashboard read tier is BED-01+. Expect the row to appear on the next scheduled rollup.
5. **Confirm bounded behaviour** — repeat step 2 twenty times back-to-back (any fast slash-command like `/help` will do). The p95 wall time from `sessionEnd` to `.mcp-push.log` new line should stay **≤ 2 s** (NFR-Performance). `.mcp-push.log` line count is capped at 100 — expect head-drop of the oldest entries once the cap is hit.
6. **Record the result** in your pre-release notes: date, VS Code version, Copilot Chat version, Node version, and the 20-session p95 you measured.

If any step regresses, capture the offending `.mcp-push.log` line and the last 5 rows of `activity.jsonl`, then file against `ING-05` or its follow-up feature.

## 5. Troubleshooting `.mcp-push.log`

`docs/activity/.mcp-push.log` is JSON-per-line: `{"event": <name>, "ts": <iso8601>, ...}`. Bounded at **100 lines / 32 KB** with in-process head-drop rotation — oldest lines dropped on overflow. Field allowlist: `event`, `ts`, `http_status`, `error_code`, `duration_ms`, `mcp_url_host`. No `program_id`, no `user`, no command text, no bearer token, no response body.

| Event | Cause | Fix |
|---|---|---|
| `success` | Push worked; row landed at ingest. | — |
| `timeout` | MCP server stalled beyond 10 s (`TIMEOUT_MS`, single attempt, no retry). | `curl -v http://127.0.0.1:3010/mcp` — is the server up? If yes, check its logs for a blocked ingest POST. |
| `network_error` | Server not running or wrong port (`ECONNREFUSED` / `ENOTFOUND`). | Boot `services/mcp-server/` per its README, or fix `HARNESS_MCP_URL`. |
| `http_error` | MCP server responded non-2xx. `http_status` is in the log line. | Read the MCP server's stdout — likely a `program_id_mismatch` or `missing_required_field` from the ingest tier. |
| `program_id_unresolved` | Neither `HARNESS_PROGRAM_ID` nor `.harness/program.yaml program_id` (nor legacy `programId`) resolves. Row was SKIPPED — nothing written to `activity.jsonl`. | Add `program_id` to `.harness/program.yaml`, or `export HARNESS_PROGRAM_ID=<id>`. See [ADR-0015](../adr/0015-program-id-sourcing-precedence.md). |
| `journal_codec_unknown_kind` | VS Code Copilot Chat's journal introduced a `kind` value outside `{0, 1, 2}`. `codec_version` in the log line is the pinned `JOURNAL_CODEC_VERSION`. Row emission for surrounding known kinds continues; the unknown kind is skipped and logged **once per session-end**. | Report to harness maintainers with the log line and Copilot Chat / VS Code version. Not a local fix. |
| `mcp_url_non_loopback` | `HARNESS_MCP_URL` was set to a non-loopback host. Push refused before any fetch attempt (NFR-Security). | Unset the env var, or point it at `127.0.0.1` / `::1`. |

**Known workspace-resolution limitations** — the hook resolves VS Code's opaque workspace hash by scanning `workspaceStorage/*/workspace.json` for the folder URI with the **longest path match** to the current project root. Multi-workspace and multi-VS-Code-instance setups where two roots share a prefix can misattribute one session's rows. Codespaces / remote-VS-Code storage layouts are **unsupported** — the hook targets local macOS / Windows / Linux `workspaceStorage/` only.

## 6. Backward compatibility

Additive. Claude Code's [`.claude/hooks/harness-activity.mjs`](../../.claude/hooks/harness-activity.mjs) continues to work identically:

- Both producers write to the same `docs/activity/activity.jsonl`, upserting on `(session_id, cmd_ts)` — the [`usage_events`](../requirements/data.md) unique constraint.
- Both producers spawn the same `.github/hooks/harness-mcp-push.mjs` for the MCP push.
- `source` differentiates: `"copilot"` vs Claude Code's own value. The `program_id` precedence in [ADR-0015](../adr/0015-program-id-sourcing-precedence.md) is the shared contract every future producer (Claude Code, Codespaces bridge, non-VS-Code editors) MUST honour.

## 7. Reference

- Story: [`docs/stories/ING-05.md`](../stories/ING-05.md)
- PRD: [`docs/features/ING-05/REQUIREMENTS.md`](../features/ING-05/REQUIREMENTS.md)
- Plan: [`docs/features/ING-05/PLAN.md`](../features/ING-05/PLAN.md)
- ADR-0015 (row-level `program_id` precedence): [`docs/adr/0015-program-id-sourcing-precedence.md`](../adr/0015-program-id-sourcing-precedence.md)
- Hooks: [`.github/hooks/copilot-activity.mjs`](../../.github/hooks/copilot-activity.mjs), [`.github/hooks/harness-mcp-push.mjs`](../../.github/hooks/harness-mcp-push.mjs)
- MCP server: [`services/mcp-server/README.md`](../../services/mcp-server/README.md)
