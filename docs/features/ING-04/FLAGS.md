# Agent flags — ING-04

Raised by workers during implementation. Triage via `/arh-human-review ING-04` before commit.

---

### AF-01: pyproject dev-deps style differs from services/api convention

- **status**: carry-forward (2026-09-14 — non-blocking; sibling service per D-01, install path is `pip install -e .[dev]`; convention decision deferred to a cross-service cleanup)
- **kind**: risky-pattern
- **source**: services/mcp-server/pyproject.toml
- **raised_by**: T-01 (implementation-agent)
- **raised_at**: 2026-09-14
- **summary**: `services/mcp-server/pyproject.toml` uses `[project.optional-dependencies]` `dev` to align with the README's `pip install -e .[dev]` instruction. `services/api/pyproject.toml` uses `[dependency-groups]` `dev` (PEP 735, `uv`-native). Both work with `uv sync --extra dev`; a bare `uv sync` skips dev deps under the optional-dependencies form. Flag for cross-service convention decision.
- **remediation options**: (a) accept as-is (D-01 declares mcp-server a separately-deployed sibling — deploy pipeline is independent, `pip`-installable is a valid target); (b) switch to `[dependency-groups]` dev for parity with services/api and update README install command.

---

### AF-02: push_activity reads wrong response keys from backend

- **status**: resolved (fix pass round 1, 2026-09-14)
- **kind**: contract-drift
- **source**: services/mcp-server/src/agentrise_mcp/tools/push_activity.py
- **raised_by**: T-08 (implementation-agent)
- **raised_at**: 2026-09-14
- **summary**: `push_activity` accumulates `rows_received / rows_upserted / rejections` from the `/api/ingest/activity` response. The actual backend schema `IngestFilesResponse` (services/api/app/schemas/ingest_files.py) ships `{received, valid, inserted, updated, rejected, rollup_summaries}` — different names. Tool unit tests pass (they mock the same wrong shape) but the tool will read zeros/empty-list against the real backend. Fix in fix-loop: update push_activity to consume real backend keys OR align backend to MCP shape (former is correct — the backend is the source of truth per ADR-0013). PLAN F-07 and PRD FR-2 both use language that doesn't match either shape exactly, needs settling.
- **remediation**: rework `push_activity.py` result envelope to use `received / valid / inserted / updated / rejected / rollup_summaries` from the response. Update the 3 test files to match. This will be picked up by the Step 2 validation-agent's real-backend integration check.

---

### AF-03: push_activity missing-token error string diverges from PLAN R-08 envelope

- **status**: resolved (fix pass round 1, 2026-09-14 — envelope now `{error: "missing_ingest_token", message: "..."}` per PRD FR-6)
- **kind**: contract-drift
- **source**: services/mcp-server/src/agentrise_mcp/tools/push_activity.py
- **raised_by**: T-08 (implementation-agent)
- **raised_at**: 2026-09-14
- **summary**: Tool returns `{success: false, error: "AGENTRISE_INGEST_TOKEN is required but not set"}` (task-prompt literal). PLAN R-08 mitigation asserts the structured envelope `{success: false, error: "missing_ingest_token", message: "..."}` (short error code + separate human message). Task prompt won at dispatch; flagging for alignment before T-09 replicates the same choice.
- **remediation**: pick one — recommend PLAN's structured form because it's easier for MCP clients to switch on. Update T-08's push_activity + T-09's push_artifacts + their tests. Fix in fix-loop.

---

### AF-04: design dimension marked N/A — no UI surface

- **status**: accepted-n/a (2026-09-14 — backend/MCP tool; state.json `design: n/a`; PRD NFR-Accessibility=N/A)
- **kind**: evidence-na
- **source**: docs/config/project-commands.yaml (`design_check:` unset for backend-only stack)
- **raised_by**: evidence-pass (implementation-agent)
- **raised_at**: 2026-09-14
- **summary**: `design` dimension of the six-dimension evidence pass is N/A for ING-04. The MCP server is a backend/tool surface with no rendered UI (state.json `design: n/a`, PRD NFR-Accessibility declared N/A). Confirm N/A at `/arh-human-review` before commit-PR.
- **remediation**: engineer accepts N/A at triage. No code change.


