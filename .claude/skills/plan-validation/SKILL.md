---
name: plan-validation
description: 6-dimension PLAN.md completeness rubric — wiring, docs, runner-setup, cross-section, config drift, decision-promotion. Pass = 0 violations. Mirrors `requirement-validation` for planning.
when_to_use: Validating PLAN.md before the tracker-push phase in /arh-plan-implementation. Catches missing wiring entries, missing docs tasks, missing test-runner setup tasks, cross-section mismatches (including a cyclic or write-conflicting task DAG), missing `docs/config/{project-commands.yaml,stack-smoke.md}` updates for new deps / services / ports, and heavy-blast decisions left unpromoted to an ADR.
user-invocable: false
allowed-tools: Read Write Edit
---
# Plan Validation

The `requirement-validation` rubric catches story-level gaps before /arh-research; this rubric catches PLAN-level gaps before /arh-implement. Same architectural intent: **a downstream phase's input must be verified complete, not trusted**.

## Why this rubric exists

Common shipped-broken patterns: a frontend root file created but never wired into the app router; a new service entry without a README; e2e test cases declared but no test-runner config task; a new dep added without `preflight:` update. Each gap traces to PLAN.md omitting the needed file or task. The implementation-agent obeys the surgical-changes rule correctly — it does ONLY what PLAN says. **Incomplete plan in → incomplete code out.**

## Rubric — 6 dimensions, all pass/fail

| Dimension | Pass | Fail |
|---|---|---|
| **Wiring** | Every NEW module in `file_plan` (action `create`) has its entry-registration site listed as a `modify` entry in `file_plan` | New module created but its entry-point / import-host / config-mount NOT listed as `modify` |
| **Docs** | Each of the 4 doc triggers (T1 runnable surface / T2 new HTTP route / T3 new env var / T4 new service or port) that fires has its required documentation task in the task table | Trigger fires and no matching documentation task in the task table |
| **Runner-setup** | Any TC declared in test-strategy with `type: e2e \| performance \| contract` has its runner install + config task in the task table | E2E / performance / contract TCs declared but their runner setup carried-forward or absent |
| **Cross-section consistency** | `predecessors` is acyclic and every edge resolves. Every TC type in test-strategy → matched task in `tasks`. Every `file_plan` entry → covered by ≥1 task's `files[]`. Every task `files[]` id → exists in `file_plan`. No two DAG-independent tasks share a file (parallel-safety) | A `predecessors` cycle / self-reference / dangling edge, OR any TC type without backing task, OR a `file_plan` entry no task touches, OR a task referencing a missing `F-NN`, OR two unordered tasks writing the same file |
| **Config drift** | Any feature change that adds a runtime dep / service / port has a matching task editing `docs/config/project-commands.yaml preflight:` or `docs/config/stack-smoke.md` | Dep / service / port added in file table or task wording, but config files left stale → bootstrap-time config no longer matches the deployed feature |
| **Decision-promotion** | Every `DECISIONS.md` entry tagged `blast:system` / `blast:data` / `rev:effectively-irreversible` carries an `adr:ADR-NNNN` slug (promoted to a full ADR) | A heavy-blast / irreversible decision left at `adr:—` — its rationale lives only in the disposable per-feature log, lost to the next story that builds on that schema / dependency |

**Total: 6 dimensions. Pass = 6/6. Fail = any violation.**

No weighted score (unlike `requirement-validation`). PLAN completeness is binary — either every module is wired, or it isn't.

## Detection mechanics

### Wiring dimension

For every `file_plan` entry with action `create`:

1. Identify the module's CONSUMING entry-point. Common patterns:
   - Frontend component → consumed by parent route file or barrel index
   - Backend module → consumed by package init exports or framework wiring (router include)
   - Service / hook / store → consumed by composition file
2. Verify that consuming file appears as a `modify` entry in `file_plan`.
3. **Allowed exception**: if the new file is itself a leaf (test file, fixture, README, ADR), no wiring required.

When a new file's consumer cannot be inferred from filename/path, surface a `[NEEDS CLARIFICATION: which file registers <new file>?]` marker and FAIL the dimension.

### Docs dimension

Four triggers. Each fires independently; the dimension fails if any firing trigger lacks its required documentation task.

| Trigger | Detection | Required task |
|---|---|---|
| **T1 New runnable surface** | File table creates a new top-level project root (new `package.json` / `pyproject.toml` / equivalent), a new server/CLI entry file at a fresh top-level, OR story PRD names a new user-facing service | Task table contains a `docs(readme)` task touching ROOT `README.md` — including how to start the new surface (port, env, command) |
| **T2 New HTTP route** | File table creates / modifies any router file declaring a new path (e.g. method + URL pattern) | Task table contains a task updating EITHER root `README.md` API section OR `docs/openapi/<name>.yaml` OR `docs/api/<name>.md` — with the route, method, request schema, response schema |
| **T3 New env var** | File table creates / modifies any settings/config module declaring a new env var, OR PRD/PLAN body cites a new env var | Task table contains a task updating BOTH root `README.md` env table AND `.env.example` with var name + default + acceptable range |
| **T4 New service entry / port** | File table creates a new top-level service dir (`services/<new>/`, `apps/<new>/`); OR `docker-compose.yml` adds a service; OR migration introduces a new external dependency | Task table contains a task updating root `README.md` "Prerequisites" + run-instructions sections |

For firing triggers, the failing-dimension report MUST name the trigger (e.g. `Docs: FAIL — T2 (new HTTP route POST /api/<resource>) — no task updates root README API section or docs/openapi/`).

Pass criterion: the docs task target file MUST be **root `README.md`** (or root-level OpenAPI/API doc), not a service-nested README — unless the trigger is itself service-nested AND the service-nested README is the user-facing primary doc.

### Runner-setup dimension

For every TC in `docs/test-cases/<story>.json` with `type` in `{e2e, performance, contract}`:

1. Identify the required runner from the project's declared `test_runner` per stack in `harness.yaml`.
2. Verify the task table contains an install + config task for that runner. For e2e/perf/contract runners that's typically: runner config file + browser/driver install + invocation script.
3. "Carry-forward" / "deferred" is NOT acceptable for runner setup when TCs of that type already exist in the test-case JSON.

### Cross-section consistency dimension

Reads `tasks.json` (`file_plan` + `tasks`) and PLAN.md §7 test-strategy. Five sub-checks — run **acyclic first**: the other checks walk `predecessors` transitively, and that walk only terminates on an acyclic graph.

- **Acyclic (DAG well-formedness)**: the `predecessors` edges contain no cycle and no self-reference, and every id named in a `predecessors` list exists in `tasks[]`. Walk the graph (DFS with a visiting-set, or repeatedly strip tasks whose predecessors are all already stripped — anything left is in a cycle). FAIL names the cycle path; fix = drop the edge that closes it. This is the check the `tasks.json` schema means by "cycles rejected at write time": a cycle makes the `/arh-implement` scheduler's ready set permanently empty, so the story never drains and the run has to be escalated by hand.
- **Every TC type → matched task**: for each declared test-strategy `type` (unit/integration/e2e/perf/security), some `tasks[]` entry produces tests of that type
- **Every `file_plan` entry → covered by a task**: every `F-NN` in `file_plan` appears in at least one `tasks[].files`
- **Every task → real file refs**: every id in a `tasks[].files` exists in `file_plan`
- **Parallel-safety (DAG write-conflict)**: no two **DAG-independent** tasks (neither transitively precedes the other via `predecessors`) share a file — i.e. their `files[]` (resolved via `file_plan`) must be disjoint. Two unordered tasks writing the same file would corrupt a parallel run. FAIL names the pair + the shared file; fix = add a `predecessors` edge between them or split the file.

Mismatches indicate one section was edited without updating the others, or a missing dependency edge.

### Config drift dimension

`docs/config/project-commands.yaml` (preflight) and `docs/config/stack-smoke.md` are written at `/arh-init` time per the declared stacks. Day-2 evolution — new deps, new services, new ports — drifts the config silently unless each feature updates it. Drift produces a real failure mode: `validate-feature` Phase 1 preflight is stale (missing-dep cascade), Phase 2b stack-smoke is stale (new service never booted), post-edit hooks keep using the old commands.

Three triggers. Each requires a config-file edit task in the PLAN task table.

| Trigger | Detection | Required task |
|---|---|---|
| **C1 New runtime dep** | File table modifies any package manifest or lockfile for the project's language(s) (the patterns skill body names which files those are); OR task wording matches an install verb (`add`, `install`, `require`, etc.) followed by a package name | Task table contains a task touching `docs/config/project-commands.yaml preflight:` — appending an install or smoke-import command for the new dep |
| **C2 New service entry** | File table creates a new top-level service dir; OR `docker-compose.yml` adds a service; OR `harness.yaml` adds a stack | Task table contains a task touching `docs/config/stack-smoke.md` — adding a new `# <stack-id>` section with `Run:` / `Docker:` bullets (and `Migrate:` when schema migration required) |
| **C3 New port / endpoint host** | Task wording introduces a new port; OR an env var named `*_PORT` / `*_HOST` / `*_URL` is added; OR a server bind/listen invocation changes a port number | Task table contains a task updating the existing `# <stack-id>` section's `Run:` / `Docker:` bullets in `docs/config/stack-smoke.md` |

Two related but DISTINCT dimensions:

- **C1 differs from Runner-setup**: Runner-setup is about test runners (e2e, perf, contract); C1 is about runtime deps the application itself imports. Both can fire for the same PLAN — both must pass.
- **C2 differs from Docs T4**: Docs T4 requires root README service-prerequisites entry; C2 requires `stack-smoke.md` entry. Both must fire and pass — README is for humans, stack-smoke.md is for automation.

When detection fires, FAIL the dimension with a specific message: `Config drift: FAIL — C1 (new dep: <pkg>) — no task updates docs/config/project-commands.yaml preflight:`.

### Decision-promotion dimension

Reads `docs/features/<id>/DECISIONS.md`. Every entry header is greppable by design:
`### D-NN: <title> · blast:<radius> · rev:<reversibility> · adr:<id|—>`.

For every entry:

1. Parse the `blast:`, `rev:`, and `adr:` slugs from the header line.
2. The entry **must be promoted** (`adr:` ≠ `—`) when `blast:` ∈ {`system`, `data`} OR `rev:` = `effectively-irreversible` — the `decide` skill's promotion rule (§ *When a decision must be promoted to a full ADR*). That rule is the single source of truth; do not re-derive it here.
3. FAIL if any such entry carries `adr:—`. A `feature` / `service` entry that is `mechanical` / `medium` to reverse needs no ADR — do NOT flag it (over-promotion floods `docs/adr/` and is its own anti-pattern).

FAIL names the offending entries + the triggering slug:

```
Decision-promotion: FAIL — D-01 (blast:data) and D-05 (blast:data) resolve durable-schema
changes but are logged adr:— — promote each to docs/adr/ via adr-template and set the adr: slug.
```

The gate exists because a heavy decision left in the per-feature log is lost the moment the story folder is treated as done — the next story that builds on that schema or dependency has no ADR to read, and an auditor asking "why was the shipped schema changed?" finds the answer only in a log the system itself calls disposable. The `blast:` / `rev:` slugs were designed as the machine half of exactly this check.

## Self-correction loop

When validation fails (any dimension):

1. Hand back to `impl-planning-agent` with the failing dimension(s) and one-line directives per dim (see skill `plan-authoring` § Plan validation (rubric) failure-handling table for verbatim directives).
2. Agent revises PLAN.md to address each directive.
3. Re-run rubric.
4. **Cap at 2 rounds.** After round 2 fail → mark `Status: ESCALATED` in PLAN.md header; surface remaining gaps to user; do not proceed to /arh-implement.

## Output report (appended to PLAN.md)

```
## Plan validation

- Date: <iso8601>
- Verdict: PASS | FAIL | ESCALATED
- Wiring:                <PASS|FAIL>  (<details>)
- Docs:                  <PASS|FAIL>  (<details>)
- Runner-setup:          <PASS|FAIL>  (<details>)
- Cross-section:         <PASS|FAIL>  (<details>)
- Config drift:          <PASS|FAIL>  (<details>)
- Decision-promotion:    <PASS|FAIL>  (<details>)
- Rounds:                <N>
```

A passing plan can be referenced downstream as "validated PLAN" — `/arh-implement` Step 0 trusts that wiring is complete and required tasks exist.

## Anti-pattern

- Skip the rubric to "save time". A plan failure is much cheaper to fix than re-doing implementation after deployment.
- Mark a dimension PASS by deleting the failing item from the file table or test-strategy. The dimension fails because something IS missing — removing the trigger doesn't fix the gap, it hides it. The agent MUST add the missing wire/task/setup, not remove the trigger.
- Allow "carry-forward" exit for runner-setup when TCs of that type exist. The carry-forward exit is for risks accepted via ADR — not for infrastructure required to even RUN the declared tests.
