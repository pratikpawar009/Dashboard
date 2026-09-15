# ADR-0015: Activity-hook `program_id` sourcing precedence — env → `.harness/program.yaml → program_id` (legacy `programId`) → skip

- Status: Accepted
- Date: 2026-09-15
- Deciders: impl-planning-agent (ING-05), product-owner (single-approver mode)

## Context

`services/api/app/schemas/ingest_files.py::ActivityRowIn` declares `program_id: str = Field(...)` as **required**. The service layer additionally enforces envelope↔row match on ingest and emits `program_id_mismatch` when a row's `program_id` differs from the envelope's. During ING-04's live end-to-end validation (2026-09-14, PR #323, commit `7e2b8c6`), a Copilot Chat sessionEnd wired to the shipped `.github/hooks/copilot-activity.mjs` produced 141 rows in `docs/activity/activity.jsonl` that lacked a `program_id` field entirely. Every row was rejected at the ingest tier with `missing_required_field`. The dashboard's Activity panel stayed empty; the pipeline delivered zero visible signal.

Two independent local sources for `program_id` exist on a developer's machine and are already conventions elsewhere in the harness:

- **`HARNESS_PROGRAM_ID`** environment variable — used by `harness-mcp-push.mjs` today to override the envelope-level `program_id` when spawning the MCP push. Deployment-time override; mirrors ING-04's `AGENTRISE_INGEST_TOKEN` env-var pattern (ING-04 D-06 / ADR-0014).
- **`<workspace_root>/.harness/program.yaml`** — committed to the repo, canonical single source of truth for `.harness/*` reads across the harness (ING-04 D-04). Top-level `program_id` key. Legacy variant `programId` is present in some older program.yaml files that have not been migrated.

The MCP tool `push_activity` (`services/mcp-server/src/agentrise_mcp/tools/push_activity.py`) does NOT patch per-row `program_id`; ING-04's contract explicitly hands the row's `program_id` back to the hook that produced the NDJSON. This ADR is the row-tier binding; ING-04 owns the envelope tier.

Three candidate policies were considered:

1. **Env-first with YAML fallback, skip on unresolved (the chosen policy).**
2. **YAML-first with env override.** Rejected — env is the operator's deployment lever and must win over a committed file for local reruns / multi-program development environments.
3. **Default to a placeholder like `"unknown"` when both sources are absent.** Rejected — the placeholder would fail the envelope↔row match at the ingest tier and produce the same 141× regression under a different reason code (`program_id_mismatch` instead of `missing_required_field`). Silent-drop of the sessionEnd is strictly safer than silent-poisoning of the pipeline.

## Decision

`.github/hooks/copilot-activity.mjs` resolves `program_id` at row-assembly time — BEFORE the NDJSON append/upsert into `docs/activity/activity.jsonl` — using the following precedence, top-to-bottom, first-match wins:

1. `process.env.HARNESS_PROGRAM_ID` when defined AND non-empty (empty string treated as absent, matching FR-6 wording in `services/mcp-server/`).
2. `<workspace_root>/.harness/program.yaml` parsed as YAML; top-level key `program_id`.
3. Same file, legacy key `programId` (accepted on read only — writes always use `program_id`).
4. Neither source resolves → write exactly one `{"event":"program_id_unresolved","ts":<iso>}` line to `docs/activity/.mcp-push.log` and SKIP the NDJSON append for that session-end. Do NOT emit a row with an empty, null, or placeholder `program_id`.

Every row appended to `activity.jsonl` MUST carry a non-empty `program_id` string matching whichever source resolved above. Future harness-side hooks (Claude Code, Codespaces, non-VS-Code editors) that also write to `activity.jsonl` MUST honour this same precedence to keep the ingest tier's envelope↔row check consistent across producers.

## Consequences

- **Positive**:
  - Eliminates the ING-04 live-E2E 141× `missing_required_field` regression class. Every Copilot Chat sessionEnd either produces a valid row or produces zero rows plus a diagnostic log line — never a partially-valid row that will be silently rejected downstream.
  - Codifies a single source-of-truth ordering that the next producer of `activity.jsonl` rows (Claude Code bridge in a future story, or a Codespaces bridge) can adopt without re-litigating the precedence.
  - Env-first ordering supports the local-dev multi-program workflow (a developer working on two programs in one workspace flips `HARNESS_PROGRAM_ID` per shell session without editing `program.yaml`).
  - The "skip on unresolved" rule keeps failure modes loud in `.mcp-push.log` while keeping them silent to the Copilot Chat UX (fire-and-forget contract preserved per ING-05 AC-2 / AC-5).

- **Negative**:
  - A sessionEnd with neither source configured produces zero visible activity on the dashboard. The developer's Copilot Chat use for that session is invisible until they set the env var or add `program_id` to `.harness/program.yaml`. Mitigated by `docs/how-to/copilot-chat-setup.md` which lists this as the first prerequisite and by the `.mcp-push.log` diagnostic line.
  - Legacy `programId` key support is a permanent read-time compatibility shim. Future cleanup would need a mass-migration of committed `.harness/program.yaml` files across all consuming repos.

- **Reversible?** Yes, mechanically. Reverting to a different precedence (e.g. YAML-first) is a two-line edit to `copilot-activity.mjs` and a rewrite of the fixtures for `ING-05-TC-01`. No data migrated under the choice; already-appended rows in `activity.jsonl` remain valid regardless of which source produced their `program_id`. Cost to undo: hours, not days.
