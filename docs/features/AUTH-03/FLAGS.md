# AUTH-03 — Agent flags

Observations raised by implementation agents during `/arh-implement`. Each block is
triaged by `/arh-human-review AUTH-03`; commit-PR (Step 5) refuses to run while any
block is `status: open`.

### AF-01: `persona` is an optional field on the two `rbac_check_*` events

- kind: risky-pattern
- task: T-01
- source: services/api/app/core/rbac.py:_EVENT_OPTIONAL_FIELDS
- status: open

**Observation.** `AUTH-03-FR-2`/D-02 specify `rbac_check_org_access` and
`rbac_check_governance_visibility` as carrying `{user_id, persona, outcome, timestamp}`,
but `AUTH-03-FR-1` also requires those same events to be emitted on the
resolver-failure denial path — where no persona value exists. T-01 resolved the
intersection by making `persona` the one optional field on those two events: present
whenever resolution succeeded (authorized, or a denial computed from a resolved
persona), omitted only on `_resolve_persona_or_deny`'s two `except` branches. Precedent
cited: AUTH-02's own optional `tier3_latency_ms` on `persona_mapping_loaded`.

**Orchestrator adjudication (not escalated to the PO).** D-02/C-2's allowlist is an
upper bound — "no `email`, no `groups`, no JWT claims, no raw session context" — so
omitting a field the code cannot know does not breach its intent, whereas adding one
would. TC-20/TC-21 assert the exact key set only on the authorized path; TC-17/TC-18/
TC-19 assert only log level and `outcome`. The choice therefore contradicts no locked
assertion and no logged decision, which is why this is a flag rather than a
`QUESTIONS.md` clarify round.

**What a triager should decide.** Whether log-schema consumers (alerting, the
downstream AUTH-04 success signal in `REQUIREMENTS.md` § Rollout plan) want a constant
key set across outcomes — i.e. `persona: None` on the resolver-failure branch — instead
of an absent key. Either satisfies the tests; only one is stable for a
schema-on-read consumer.

### AF-02: `design_check` evidence dimension is N/A — no tool wired

- kind: evidence-na
- task: evidence-pass
- source: docs/config/project-commands.yaml
- status: open

N/A on two independent grounds: `project-commands.yaml` has `design_check: ""` (no
a11y / console-error-scan / perf tool has been chosen or installed for this project
yet), and `docs/features/AUTH-03/state.json` has `design: "n/a"` (AUTH-03 is
backend-only — no UI surface, no `DESIGN.md`). Accepted as N/A rather than PASS.

For this feature the second ground alone is sufficient and permanent: a check library
with no route or screen surface has nothing for a design check to inspect. The first
ground is the durable project-level gap — it will recur on every UI story until a tool
(e.g. axe-playwright or pa11y-ci against `apps/web`) is chosen and wired into
`design_check:`.

### AF-03: web `runtime` evidence is boot-only — no render check available

- kind: evidence-na
- task: evidence-pass
- source: docs/config/project-commands.yaml
- status: open

The Next.js runtime dimension was proven by boot + `GET / -> 200` only; `render_check`
is `unavailable` because `project-commands.yaml` has `test_e2e: ""` (no Playwright /
Cypress declared in ADR-0001). AUTH-03 changes nothing under `apps/web` — that stack
was booted solely to prove the whole runnable surface still boots. Recorded so the
gap is visible on the first story that does own UI, not as a defect of this one.

### AF-04: pre-existing `ruff format` drift in services/api/README.md

- kind: inconsistency
- task: evidence-pass
- source: services/api/README.md:26
- status: open

A supplementary `uv run ruff format --check .` (NOT part of the canonical `lint:`
command, which is `ruff check .` and passes) reports formatting drift inside the
pre-existing `## Session factory` section. Verified pre-existing: byte-identical to
`git show HEAD:services/api/README.md` since commit `1d3f740` (AUTH-02), and this
feature's diff has no hunk at that line — T-07's change was insertion-only, 66
additions / 0 deletions.

Deliberately not fixed. `.claude/rules/surgical-changes.md` forbids improving adjacent,
unrelated content even inside a file this feature otherwise modifies. Carry-forward
candidate for whoever next owns that section.

---

## Triage record — 2026-08-31

All four flags above are **`status: defer`**, not `accept`.

No `/arh-human-review AUTH-03` round was run. The engineer directed commit + PR directly, so
`/arh-implement` Step 5's RC4 agent-flag gate was passed by explicit user direction rather than
by triage. This is recorded rather than papered over: none of the four has been accepted on its
merits by a human, and all four are reproduced in the PR body so a reviewer encounters them
before merge.

Still open on the merits:

| Flag | Needs a decision on |
|---|---|
| AF-01 | absent `persona` key vs `persona: null` on the resolver-failure denial — a log-schema-stability choice, not a correctness one |
| AF-02 | project-level: no `design_check` tool wired (permanent N/A for this backend-only story) |
| AF-03 | project-level: no E2E/render tool wired |
| AF-04 | pre-existing `ruff format` drift at `services/api/README.md:26`, outside this diff |
