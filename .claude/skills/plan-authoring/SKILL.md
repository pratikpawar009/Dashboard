---
name: plan-authoring
description: Author PLAN.md — pinned 7-section order, DECISIONS.md log, DATA-DESIGN.md, F-NN file plan, T-NN tasks, plan-validation rubric, test strategy. Used by impl-planning-agent.
user-invocable: false
---
# Plan authoring

The method and formats for converting REQUIREMENTS.md into PLAN.md. Apply the sections in order.

Phase numbering used throughout: 1 = ADRs, 2 = File plan, 3 = Tasks, 3b = Plan validation, 4 = Test strategy, 5 = Tracker subtask (the tracker push runs in the `/arh-plan-implementation` orchestrator, not here).

## PLAN.md pinned section order (mandatory)

Every emitted `PLAN.md` MUST carry these top-level sections in this exact order, with this exact spelling and numbering. No extra `## `-level sections. Sub-sections (`### `) appear inside each section as documented in the step files.

1. `## 1. Architecture Decisions`
2. `## 2. File and Module Plan`
3. `## 3. Module Hierarchy`
4. `## 4. State and Data Management`
5. `## 5. Task Breakdown`
6. `## 6. Carry-Forward Risks and Conditions`  *(merges accepted risks + GO-WITH-CONDITIONS conditions; no separate "Conditions for GO" or "Addressing Research Conditions" section)*
7. `## 7. Test Strategy`

Plus the closing rubric block (`## Plan validation` — written by step 03b).

Lint rule **F-051** (warn) fires on any PLAN.md whose `## ` section set deviates from this list or whose numbering is out of order.

### §1, §2, §4 and §5 are pointers — the machine data lives beside PLAN.md

PLAN.md is the human design narrative (module design, risks, test strategy).
Four sections point at their real artifact instead of inlining it:

- **§1 body** is a one-line pointer: *"Technical decisions are recorded in `DECISIONS.md`
  (this feature's decision log)."* — the decision entries live there, not in PLAN.md.
- **§2 body** is a one-line pointer: *"File plan (`F-NN` → path/action) is maintained in
  `tasks.json` `file_plan`."* — then the **Module hierarchy** narrative (which is design, not
  data) follows in §3.
- **§4 body** is a one-line pointer: *"State & data design is maintained in `DATA-DESIGN.md`."*
  — the data model / migrations / ownership / classification / consistency / caching /
  ephemeral state / query-path performance / contract (API/interface) / async live there (see
  § State and data design below). When
  the feature is fully stateless, §4 body is instead the single line *"No state or data
  concerns."* and no `DATA-DESIGN.md` is written.
- **§5 body** is a one-line pointer: *"Task DAG + live status is maintained in `tasks.json`
  `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG."*

The 7 headings stay (F-051 checks headings + order, not content). No inline decision/file/task/data
content — duplicating it in markdown would drift from `DECISIONS.md` / `tasks.json` / `DATA-DESIGN.md`.

### Forbidden patterns

- `## 2. Cross-Feature Dependency Notes` — fold into §6 as `### Cross-Feature Dependency Notes`
- `## 8. Conditions for GO` — fold into §6 as `### Conditions for GO (research_verdict GO-WITH-CONDITIONS)`
- `## 9. ADR Index Update` — promotion notes live inside the relevant entry in `DECISIONS.md`
- `## 7. Addressing Research Conditions` — see §6 (conditions go inside §6 sub-section)
- Descriptive task IDs (e.g. `T-MIGRATION`, `T-SEED`, `T-ADR`) — `task_id` MUST be `T-NN` zero-padded numeric (`T-01..T-99`)
- An inline file/task table in PLAN.md — the file plan + task DAG live in `tasks.json` (`file_plan` keyed by `F-NN`, `tasks[]`); PLAN.md §2/§5 are pointers only

## Architecture decisions (the decision log)

Goal: capture every non-trivial decision the implementation will commit to. One entry per decision in `docs/features/<id>/DECISIONS.md`; full ADR (under `docs/adr/`) only for a decision that **outlives this story**.

### When to write an ADR

"Outlives this story" is decided mechanically by the `blast:` / `rev:` slugs — the single rule lives in the `decide` skill (§ *When a decision must be promoted to a full ADR*) and is the source of truth. In short: promote when `blast:` is `system` or `data`, or when `rev:` is `effectively-irreversible`. A `feature` / `service` choice that is `mechanical` / `medium` to reverse stays in DECISIONS.md only.

Common cases and the slug they carry:

| Decision flavour | Slug | ADR? |
|---|---|---|
| Database / durable-state schema change | `blast:data` | yes |
| New external dependency, cross-service change | `blast:system` | yes |
| Anything migrated under the choice — rollback = data loss | `rev:effectively-irreversible` | yes |
| Library pick, pattern, wiring inside one service, easily reversed | `blast:feature`/`service` + `rev:mechanical`/`medium` | no — DECISIONS.md only |
| Renaming a function, internal helper module | — | no (not decision-log-worthy) |

`plan-validation`'s **Decision-promotion** dimension enforces this: a `blast:{system,data}` or `rev:effectively-irreversible` entry left at `adr:—` fails the plan.

### Decision-log entry format (lean)

Append each entry to `docs/features/<id>/DECISIONS.md` — the feature's decision log. PLAN.md §1 stays a one-line pointer to it (§1/§2/§5 are all pointers; see above). **Header is a single line** carrying the id, title, and the machine-greppable slugs; no separate Status / Date / Deciders block.

```
### D-NN: <one-line title> · blast:<feature|service|system|data> · rev:<mechanical|medium|effectively-irreversible> · adr:<ADR-NNNN|—>

**Context**: <one paragraph; the constraint that makes this a decision, not a default>

**Decision**: <one paragraph; the choice + specifics>
```

`blast:` and `rev:` are the blast-radius and reversibility slugs (`decide` skill § Field guidance). `adr:` is the full-ADR id once promoted, else `—`.

### When to omit `Context`

Never. Context is what tells readers why this is a decision at all. If the context is "we need a way to do X" with no constraint, the decision isn't decision-log-worthy — drop it.

### Promotion to full ADR

If a decision will outlive this story, also write a full ADR using `adr-template`:

- Path: `docs/adr/<NNNN>-<slug>.md`
- Update `docs/adr/README.md` index.
- Set the entry's `adr:` slug to the ADR id (`adr:ADR-0017`).

### Writing the log (mandatory)

Invoke the `decide` skill to append each entry to `docs/features/<id>/DECISIONS.md`. One decision → one entry. The log is both the human narrative and the greppable record (header slugs) — consumed by `/arh-implement` context-load, `/arh-review` code review, and the playbook site. PLAN.md §1 is a pointer only; do not duplicate entries there.

See `.claude/skills/decide/SKILL.md` for the entry format, field guidance, and anti-patterns.

### Anti-pattern

Don't author ADRs for trivial choices. Don't bury an ADR-worthy choice inside a task description. If three readers would each pick a different solution from the same prompt, write the ADR.


## File and module plan

Goal: list every file to create or modify, and the module hierarchy with explicit input/output contracts.

### File plan → `tasks.json` `file_plan`

The file plan is data, so it lives in `tasks.json` `file_plan` (an object keyed by `F-NN`),
NOT as a markdown table in PLAN.md. PLAN.md §2 carries only the pointer.

```json
"file_plan": {
  "F-01": { "action": "create", "path": "src/checkout/promoStack.ts", "reason": "new logic per D-01" },
  "F-02": { "action": "modify", "path": "src/api/routes/promos.ts",   "reason": "add GET /preview" },
  "F-03": { "action": "create", "path": "tests/integration/promo-stack.spec", "reason": "covers TC-04..TC-08" },
  "F-04": { "action": "generate", "path": "src/db/client.generated.ts", "reason": "prisma generate output — regenerated, never hand-edited" },
  "F-05": { "action": "external", "path": "kafka://orders.settled (6 partitions)", "reason": "provision topic + register avro schema" }
}
```

`action` ∈ `create | modify | generate | external`. **`generate`** = a codegen/build output —
declare it so the derived parallel-safety check can serialize two tasks that regenerate the same
artifact (the output is not a hand-edited source file). **`external`** = non-repo work keyed by a
stable identifier (a topic/keyspace, a CMS content-type, an IaC resource, a security-rules file)
so infra provisioning, content-modeling, and declarative-authz changes are reviewable lines with a
design narrative, not invisible to the diff-anchored review/evidence path. Every `F-NN` id here is
referenced by ≥1 task's `files[]` (§ Task graph). Same discipline — name every file/resource;
"various files in src/" is forbidden.

### Module hierarchy

For new or significantly-modified modules, draw a tree with input / output / public contract per node:

```
checkout/
├── promoStack
│   - input:  PromoCode[], Cart
│   - output: AppliedDiscount[]
│   - public: applyStack(codes, cart) -> AppliedDiscount[]
└── promoPreview
    - input:  PromoCode, Cart
    - output: PreviewResult { eligible, amount, reason }
    - public: preview(code, cart) -> PreviewResult
```

#### Navigation / routing map

When the feature adds pages/screens/nav, map each **route (or nav destination) → the component/handler that serves it + its render mode**. This is *presentation* routing (URL/screen → view); data endpoints and RPC/actions belong in `DATA-DESIGN.md` §9 Contract, not here.

```
routes/
├── /checkout    → CheckoutPage (server)   → uses <PromoStack>
└── /orders/:id  → OrderDetailPage (server) → fetches getOrder(id)
```

Use whatever the framework's routing actually is — the component fetches its own data (no imported "loader" vocabulary), and free-text annotations are fine for nested-layout chains, loading/error boundaries, or parallel/intercepting modals. For a mobile app this is the **nav graph** (push/pop stack + tabs + deep links), not URLs. For an event-driven backend the parallel is a **trigger map** (topic → consumer-group, or event-source → handler); include it here when the feature adds one.

The authoritative screen↔route↔render map is the PRD `## Screen inventory` (`Route`/`Render` columns); this block is the route→component wiring the implementation-agent builds. Omit for backend-only features (unless adding a trigger map) and for a UI feature with no routing change.

### Anti-pattern

Don't list "various files in src/checkout/" — name every file. The list is the contract between this plan and the implementation-agent.

## State and data design (§4 → `DATA-DESIGN.md`)

Goal: capture the feature's full state/data surface in one place so the implementation-agent builds the right data layer and reviewers can check the diff honors it. PLAN.md §4 is a one-line pointer; the content lives in `docs/features/<id>/DATA-DESIGN.md`.

**Applicability.** Write `DATA-DESIGN.md` when the feature touches ANY of: persistent data (any store), client/ephemeral state, external data sources, an API/interface surface, or async/messaging side-effects. If the feature is fully stateless (pure refactor, no store / no API / no client state / no async), write NO file and set §4 body to the single line *"No state or data concerns."* — do not scaffold an empty file.

**Fixed-checklist discipline.** `DATA-DESIGN.md` carries the ten concerns below as `## ` sections. Each is either specified OR marked `_N/A — <reason>_` so every data risk is provably considered, never silently skipped. Omit a section only when it is genuinely irrelevant to the store class (e.g. no `Migrations` for a frontend-only feature) — otherwise mark it N/A with the reason.

**Store-class-aware, not relational.** The vocabulary below leans relational for familiarity, but each concern is store-agnostic — use each section's note to pick the shape for the store class (relational table / document collection / KV / wide-column / graph / event log / client store / external API).

### `DATA-DESIGN.md` skeleton

```
# <id> — Data Design

State & data management. Each concern is specified or marked `N/A — <reason>`.

## 1. Data model
<optional diagram — erDiagram (relational) / graph or flowchart (graph, event/saga flow) / sequenceDiagram; pick what fits the store>
### <entity> (<store kind>)     <!-- postgres table / mongo collection / redis KV / dynamo single-table / cassandra wide-column / neo4j edge / kafka event / client store -->
| Field | Type | Key/Constraint | Class | Notes |
|---|---|---|---|---|
| <name> | <logical or store-native> | freeform per store — PK / FK→<t> / unique / index / partition-key / clustering-key / aggregate-id / sequence / edge(from→to, card) / required | PII \| sensitive \| — | <ownership scope, masking, embed/nesting, maps-to source> |
<!-- KV / single-table / document stores MAY use an access-pattern → index → key-condition table instead of per-entity tables. An entity mirrored across a remote store + a local cache carries a maps-to/source note. -->

## 2. Migrations
Forward (+ rollback where the store supports it; else note **forward-only**); data backfill; ordering + zero-downtime strategy if the **store/dataset** is live. Non-relational shapes count: index/GSI add + live backfill, event **upcasting** + schema-registry compatibility, projection replay, client cache-rebuild-on-corruption.

## 3. Ownership & tenancy
Which new resource is owned via which scoping (user_id / tenant_id column, key prefix, node property, separate DB), AND the **enforcement mechanism for this store class**: server guard per `.claude/rules/security-baseline.md` (`_load_owned`, 404-not-403), an RLS policy, a declarative security-rules file (e.g. `firestore.rules`), async re-validation at process time (worker/consumer outside request context), or per-user client cache-partition/wipe. Name the owned resources + the mechanism; do NOT re-state the rule.

## 4. Data classification & retention
PII/sensitive fields; encryption-at-rest; retention + deletion (soft vs hard). The active governance profile may mandate specifics.

## 5. Consistency & concurrency
Transaction boundaries; idempotency keys; how concurrent writes are serialized (locking / conditional update). For distributed / multi-store / offline stacks also state delivery + ordering semantics (at-least-once, per-partition order, read-your-writes lag) and the **reconciliation policy** (divergence rule LWW/server-wins/field-merge, replay ordering, optimistic rollback).

## 6. Caching
Keys, TTL, invalidation events. For each invalidation name the **triggering write and its ordering relative to the store commit** (e.g. "on order write, after commit → delete redis key, then revalidate CDN tag"). `no TTL — sync-invalidated` is a valid answer (offline / local-primary stores). A pure cache with no source-of-truth role is described HERE, not modeled as a §1 entity.

## 7. Ephemeral / session state
Non-durable state and where it lives: client store / context, URL-as-state (query/search params), server-held per-connection state (LiveView assigns, WebSocket), distributed ephemeral (Presence / PubSub), server session (session / flash / CSRF).

## 8. Query-path & access-path performance
Cost of the read/write paths introduced: indexes + N+1 avoidance (relational, per `.claude/rules/performance-baseline.md`); one table/view per access pattern (KV / wide-column); fan-out / traversal cost — supernodes, path explosion, hot-partition budget (graph / wide-column); **cursor/token pagination** as the first-class alternative to offset. On clients / stateful servers the axis may be over/under-fetch, frame budget, or server-held-state memory rather than server N+1.

## 9. Contract (API / interface)
The interface this feature exposes or consumes.

**If it is a registered cross-story contract** (a `### <name>` section in `docs/requirements/<kind>.md` with `produced_by`/`consumed_by`): author the concrete shape **once, there** — that shared file is what consuming stories build against — and make this section a **bookmark**, not a copy: `Contract: <name> → docs/requirements/<kind>.md#<name>`. A shared contract lives in the shared registry, never duplicated into one feature's design doc (the copy drifts).

**If it is feature-internal** (no other story consumes it): describe it inline — use the shape that fits:
- **REST** — METHOD path, request/response, status codes.
- **RPC / action** — exported function + module (e.g. `createOrder @ lib/orders/actions.ts`), input/output.
- **GraphQL** — named operations + SDL types + body-level error shape.
- **Server-rendered form** — params → redirect/flash.
- **Consumed external API** — mark `consumer` (vs `provider`) + the upstream contract depended on.

Either way, prefer the framework-generated spec as the authoritative target (`docs/openapi/<name>.yaml`, framework `/openapi.json`, `schema.graphql`) over a hand-authored duplicate; summarise + point there (docs trigger T2).

## 10. Async & messaging   <!-- N/A for purely synchronous features -->
Per message / event / job: trigger, broker/topic/queue/exchange, routing/partition key, delivery guarantee (at-least-once / …), retry + backoff, DLQ / poison-message policy, consumer dedup / idempotency key, schedule / cron, and produced-by / consumed-by.
```

**Diagram + table are store-shaped.** Use the per-entity table OR an access-pattern table (KV / single-table); the optional diagram is whichever of `erDiagram` / `graph` / `flowchart` / `sequenceDiagram` fits. Do NOT use SQL DDL or DBML — relational-only, they break for document / KV / graph / event / client stores.


## Task breakdown

Goal: decompose the implementation into independently-mergeable tasks, each with a complexity tag, predecessor list, and file refs — written to `tasks.json` `tasks`.

### Task ID and File ID rules (mandatory)

- **Task IDs** (`tasks[].task_id`) MUST be `T-NN` zero-padded numeric (`T-01..T-99`). Descriptive IDs like `T-MIGRATION`, `T-SEED`, `T-ADR` are forbidden — downstream tooling (`/arh-implement` scheduler, `harness carry-forward`, `harness analyse`) orders the DAG by numeric ord and breaks on string IDs.
- **File IDs** (`file_plan` keys) MUST be `F-NN` zero-padded numeric (`F-01..F-99`); each task's `files[]` references them. A `file_plan` entry without a resolvable `path`/`action`, or a task `files[]` id absent from `file_plan`, is a cross-section failure.
- **Section heading** MUST be `## 5. Task Breakdown` (numbered, exact case). Lint rule F-051 fires on deviation.

### Task DAG → `tasks.json` `tasks`

Tasks are data too, so they live in `tasks.json` `tasks` (an array), NOT a markdown table.
PLAN.md §5 carries only the pointer. One object per task:

```json
"tasks": [
  { "task_id": "T-01", "title": "Add PromoStack type + applyStack", "complexity": "M",
    "predecessors": [], "files": ["F-01"], "ac_refs": ["CHK-01-AC-1"], "risk_refs": ["R-01"],
    "notes": "pure; unit tests in same task",
    "status": "pending", "completed_at": null, "files_touched": [], "reason": null },
  { "task_id": "T-02", "title": "Wire applyStack into checkout flow", "complexity": "S",
    "predecessors": ["T-01"], "files": ["F-02"], "ac_refs": ["CHK-01-AC-2"], "risk_refs": [],
    "notes": "behind feature flag (per D-02)",
    "status": "pending", "completed_at": null, "files_touched": [], "reason": null }
]
```

- `files[]` references `F-NN` ids from `file_plan`.
- `predecessors[]` are `T-NN` ids (empty array = depends on nothing). They form a DAG; **reject
  cycles at write time**.
- The status block (`status | completed_at | files_touched | reason`) starts as
  `pending`/null and is updated by `/arh-implement` — it replaces the old `impl_tasks[]`.

### Parallelism is DERIVED, never stored

There is **no `[P]` field** in `tasks.json`. Concurrency is a *relation* between tasks, computed
at run time from the DAG — storing a per-task boolean would drift (same reason ordering is never
stored as a wave number). Two tasks may run concurrently iff BOTH:

1. **DAG-independent** — neither transitively precedes the other via `predecessors`.
2. **Output-disjoint** — their `files[]` (resolved to paths via `file_plan`) do not overlap.

`/arh-implement` derives the runnable set each round (see its scheduler). A task that must NOT
overlap another for a non-file reason (shared DB, port, fixture) is serialized the same way any
ordering is expressed — **add a `predecessors` edge**. There is no separate resource-tag concept;
the DAG is the single place ordering and mutual-exclusion live.

**Shared outputs are the default hazard for codegen / event / IaC stacks — declare them.** The
output-disjoint check only sees `files[]`, so two file-disjoint tasks that both regenerate a
codegen artifact (Prisma client, `*.g.dart`), both touch a framework-managed manifest
(`db/schema.rb`, `routes.rb`, lockfiles), or both use a shared runtime resource (a Kafka topic,
a Cassandra table, one shared dev/test DB) will be judged parallel-safe yet collide. For these
stacks that is the *expectation, not the exception*: list the shared artifact as a `generate`/
`external` `file_plan` entry in every task that regenerates or contends for it (so output-disjoint
serializes them), or add an explicit `predecessors` edge.

### Complexity scale

- **S** (small): a few edits in one file; <2h.
- **M** (medium): multiple files in one module; ~half-day.
- **L** (large): cross-module or migration; full day; consider splitting.

If a single task is rated XL, split it. If you cannot split, flag it as a risk in the carry-forward section.

### Sequencing

- Tasks walk the predecessor DAG in topological order.
- Tasks whose predecessors are all done, and whose `files[]` are disjoint, run in parallel (derived — see § Parallelism is DERIVED).
- Commits land sequentially regardless of parallelism (parallel diffs, sequential merge — preserves bisectability).

### The `tasks.json` file (top-level shape)

`impl-planning-agent` writes `docs/features/<id>/tasks.json` (and sets the `state.json` pointer `"tasks": {"file": "docs/features/<id>/tasks.json"}`). Shape:

```json
{
  "schema_version": 1,
  "story_id": "<STORY-ID>",
  "generated_by": "arh-plan-implementation",
  "generated_at": "<iso8601>",
  "file_plan": { "F-01": { "action": "create|modify", "path": "...", "reason": "..." } },
  "tasks": [ { "task_id": "T-01", "...": "see § Task DAG" } ]
}
```

This is the single machine source for the file plan + task DAG + live status. PLAN.md §2/§5 point to it; `/arh-implement` reads and updates it.

### Carry-forward from research — risks

PLAN.md § 6. Carry-Forward Risks and Conditions (mandatory section):

```
### 6. Carry-Forward Risks and Conditions

Risks from `docs/research/$ARGUMENTS.md` § Risk register. HIGH/CRITICAL risks must be
addressed by at least one task id from § 5; MED/LOW risks inherit their mitigation
from the research doc and need no re-statement here. Only `accepted` risks are
re-cited below — those carry forward to `pending_carry_forward[]` and require
`--accept-pending` at commit-PR time.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01    | HIGH     | T-02         |
| R-02    | HIGH     | T-02         |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale                                          |
|---------|----------|----------------------------------------------------|
| R-03    | CRITICAL | accepted (ADR-4) — documented; revisit in story-019 |

### Conditions for GO (research_verdict == GO-WITH-CONDITIONS)

<!-- Only when research_verdict is GO-WITH-CONDITIONS. List numbered conditions
     from docs/research/<id>.md § Conditions for GO mapped to addressing tasks.
     No "accepted" shortcut for conditions — conditions are non-negotiable. -->

| Cond | Condition (verbatim) | Addressed by |
|------|----------------------|--------------|
| C-1  | <condition text>     | T-06         |
| C-2  | <condition text>     | T-07         |

### Cross-Feature Dependency Notes

<!-- Optional sub-section. Use when this story's tasks depend on artefacts from
     other in-flight features (other stories' PRs, shared modules being built
     concurrently). Reference by story id and task id. Empty when none. -->
```

**Verification rule**: every HIGH or CRITICAL risk in `docs/research/$ARGUMENTS.md` MUST appear in either the "addressed by tasks" sub-table OR the "accepted" sub-table. Do NOT re-state the risk text — readers follow `docs/research/<id>.md` for context. Empty addressed-by/rationale cells are a Phase 3 fail.

**Forbidden pattern**: a separate `## Carry-forward risks` or `## Conditions for GO` or `## Addressing Research Conditions` top-level section. All conditions, accepted-risk re-cites, and cross-feature notes live INSIDE § 6 as sub-headings. F-051 fires on deviation.

### State write — carry-forward (mandatory)

`pending_carry_forward[]` is P-tier (per `docs/state/SCHEMA.md`).
For every risk-table row with `Addressed by: accepted (...)`, append to
`docs/features/$ARGUMENTS/state.json` at `.pending_carry_forward`:

```json
{
  "item_id":     "<R-NN>-<short-slug>",
  "kind":        "risk",
  "reason":      "<risk text> — accepted via <adr-id-or-rationale>",
  "owner":       "<team-or-user from PRD>",
  "added_at":    "<iso8601>",
  "added_by":    "plan-implementation/03-tasks (risk accepted)",
  "resolved_at": null,
  "evidence":    null
}
```

These entries surface in `/arh-implement` Step 5 (commit-PR) and `/arh-review`. A non-empty list
requires an explicit `--accept-pending <ids>` flag to merge (warning, not block, unless the entry
is compliance-tagged — `/arh-security-review` blocks compliance-tagged items unconditionally).

### Carry-forward from research — conditions (GO-WITH-CONDITIONS only)

When `research_verdict == "GO-WITH-CONDITIONS"` (read from per-feature state via reader rule), mirror every numbered condition from `docs/research/$ARGUMENTS.md` § Conditions for GO into the `### Conditions for GO` sub-section of § 6 (see the § 6 template above).

**Verification rule**: every numbered condition in research MUST appear in § 6 `### Conditions for GO`, and every `Addressed by` cell MUST be a task id from § 5 (no `accepted` shortcut — conditions are non-negotiable, that's why they were called out).

Phase 3 fails if:

- `research_verdict == "GO-WITH-CONDITIONS"` AND § 6 has no `### Conditions for GO` sub-section, OR
- any condition is missing from the sub-section table, OR
- any `Addressed by` cell is empty or references a non-existent task id.

When `research_verdict in {GO, SPIKE, BLOCK}`, the `### Conditions for GO` sub-section is omitted entirely. § 6 still exists for risks.


## Plan validation (rubric)

Goal: run the `plan-validation` rubric against the in-progress plan — `tasks.json` (`file_plan` + `tasks`) plus PLAN.md §7 test-strategy — before continuing to Phase 4 (test-strategy detailing) and the tracker push. Self-correct ≤2 rounds; escalate on persistent fail.

This phase exists because shipped post-mortems verified that an incomplete PLAN.md silently leads to a broken implementation: missing wiring entries → broken UI; missing docs task → no README; missing runner setup → declared e2e TCs cannot run. The implementation-agent obeys surgical-changes correctly; if the plan omits something, the code omits it too. **Catch it here, not in production.**

### Procedure

1. Load skill `plan-validation`.
2. Apply each of the 6 dimensions to the current PLAN.md:
   - Wiring (entry-registration sites listed)
   - Docs (4 triggers: T1 runnable surface / T2 new HTTP route / T3 new env var / T4 new service or port → matching docs task)
   - Runner-setup (declared e2e / perf / contract TCs → matching runner setup task)
   - Cross-section consistency (`tasks.json` `file_plan` ↔ `tasks` ↔ test-strategy; incl. DAG write-conflict / parallel-safety)
   - Config drift (new dep / service / port → `docs/config/project-commands.yaml preflight:` or `docs/config/stack-smoke.md` update task)
   - Decision-promotion (`DECISIONS.md` `blast:{system,data}` / `rev:effectively-irreversible` entries carry an `adr:` id, not `—`)
3. Compose the verdict block.
4. If any dimension fails: hand back to `impl-planning-agent` with the failing dimensions and one-line directives. Agent revises PLAN.md. Re-validate.
5. **Cap at 2 rounds.** After round 2 fail:
   - Mark PLAN.md header `Status: ESCALATED`
   - Append the round table to `docs/features/$ARGUMENTS/PLAN-ESCALATION.md`
   - Surface the gaps to the user and HALT
   - Do not proceed to Phase 4

### Round table (appended to PLAN.md)

```
### Plan validation rounds

| Round | Verdict | Failing dimensions             | Action                           |
|-------|---------|--------------------------------|----------------------------------|
| 1     | FAIL    | Wiring, Runner-setup           | impl-planning-agent revision     |
| 2     | PASS    | —                              | Continue to Phase 4              |
```

### State write (mandatory, unconditional)

`plan_validation` and `plan_validation_rounds` are P-tier (per `docs/state/SCHEMA.md`).
After PLAN.md passes the rubric, write to `docs/features/$ARGUMENTS/state.json`:

```json
{
  "plan_validation":     "PASS | FAIL | ESCALATED",
  "plan_validation_rounds": <int>,
  "last_updated":        "<iso8601>"
}
```

Also mirror `last_updated` to `docs/state/features.json[$ARGUMENTS]` per writer rule.

`plan_validation: "PASS"` is a **precondition for `/arh-implement` Step 0** (added to `phase-preconditions` matrix). `/arh-implement` aborts if the plan has not been validated.

### Failure handling for each dimension

| Failed dimension | Agent revision directive |
|---|---|
| Wiring | "Add `modify` entr(ies) in `file_plan` for the entry/registration site(s) of: <list of new modules>. The implementation-agent will not infer wiring beyond what `file_plan` lists." |
| Docs (T1 — new runnable surface) | "Add a docs(readme) task to `tasks.json` `tasks` touching ROOT `README.md` (not service-nested). Cover: how to start the new surface, required env, port. Surface introduced: <surface>." |
| Docs (T2 — new HTTP route) | "Add docs task updating root `README.md` API section OR `docs/openapi/<name>.yaml` for the new route(s): <list>. Routes shipped without contract docs fail fresh-clone usability." |
| Docs (T3 — new env var) | "Add docs task updating BOTH root `README.md` env table AND `.env.example` for the new var(s): <list>. Each var: name, default, acceptable range, what disables it." |
| Docs (T4 — new service entry / port) | "Add docs task updating root `README.md` Prerequisites + run-instructions sections for new service: <name>. Cover port, healthcheck URL, dependency on existing services." |
| Runner-setup | "Add a setup task to `tasks.json` `tasks` installing and configuring: <runner-name>. Task must touch the runner's config file and add invocation script. Order it BEFORE any task that produces TCs of that type (via `predecessors`)." |
| Cross-section | "Resolve the mismatch: <specific A vs B>. Either add the missing task / `file_plan` entry, or remove the orphaned declaration." |
| Config drift (C1 — new dep) | "Add task touching `docs/config/project-commands.yaml preflight:` — append an install or smoke-import command for the new dep(s): <list>. Use the language's idiomatic `-c \"import <pkg>\"` equivalent or the package manager's frozen-lockfile install." |
| Config drift (C2 — new service) | "Add task touching `docs/config/stack-smoke.md` — append new `# <stack-id>` section with `Run:` / `Docker:` bullets (and `Migrate:` when schema migration required). The new service is: <name> on port <port>." |
| Config drift (C3 — new port) | "Add task updating the existing `# <stack-id>` section in `docs/config/stack-smoke.md` — update `Run:` and `Docker:` bullets to use port <new-port>. Existing entry on port <old-port>." |

### Anti-pattern

- Bypass the rubric by editing the verdict line directly. The rubric is the contract that downstream phases trust; lying about it breaks the contract for everyone reading the state file.
- Resolve a wiring failure by deleting the new module from `file_plan`. The module is in scope per the story PRD; removing it doesn't remove the need — it just hides the gap until /arh-implement produces a half-built feature.
- Treat docs as carry-forward. Documentation is part of the deliverable, not a follow-up.


## Test strategy

Goal: declare exactly which tests will exist, where they live, and which TC ids they cover.

### Mapping

PLAN.md Section "Test Strategy":

```
| Layer       | Test path                                | TCs covered  | Notes                          |
|-------------|------------------------------------------|--------------|--------------------------------|
| Unit        | src/checkout/promoStack.test.ts          | TC-01..03    | pure logic                     |
| Integration | tests/integration/promo-stack.spec.ts    | TC-04..06    | uses test DB                   |
| E2E         | tests/e2e/promo-stack.spec.ts (Playwright)| TC-07..08   | runs against staging API       |
| Performance | tests/perf/promo-preview.k6.js           | TC-09        | budget: p95 < 250ms @ 100 RPS  |
| Security    | manual checklist                         | TC-10        | covered in /arh-security-review    |
```

Every TC in `docs/test-cases/$ARGUMENTS.json` must appear in this table OR be flagged as `manual: true` in the JSON.

### Coverage gates

- Unit coverage threshold (per `harness.yaml` — fall back to 80% if not set).
- E2E suite must be green pre-commit (enforced by `/arh-implement` Step 2).

### Deferred execution is constrained

A test layer may note "Execution: deferred to /arh-validate-feature" only with an explicit reason (e.g. needs staging, needs seeded external system). Even then, the task that authors the spec MUST include an **author-time smoke**: the spec compiles/lints under the runner's own parse or dry-run mode, and every route, selector, fixture, and seed user it references exists in the codebase at authoring time. "Authored but never executed" specs reliably fail on first real run — wrong runner APIs, assertions on screens that don't exist, missing seed data — and those are authoring defects that belong to `/arh-implement`, not validation-round noise.
- Performance test runs only on PRs marked `perf` label; not gating CI for every PR.

### Anti-pattern

- Don't mock the database in integration tests.
- Don't promote a unit test to "integration" by giving it a real connection without a network boundary.
- Don't write test names that mirror code structure (`testApplyPromoStack_inner_helper_path1`); name by behaviour.

### No-placeholder rule (run before Phase 5)

After Phases 1–4 are written, the agent MUST grep `docs/features/$ARGUMENTS/PLAN.md`
for placeholder phrases. ANY match = FAIL; agent self-corrects with concrete content.

**Forbidden patterns** (case-insensitive):

| Pattern | Why forbidden |
|---|---|
| `TBD`, `TBA`, `to be determined`, `to be announced` | Decision dodged |
| `TODO`, `to do`, `FIXME` | Implementation leakage; PLAN is not a backlog |
| `as appropriate`, `as needed`, `as required` | Means "I didn't decide" |
| `add error handling`, `handle errors`, `proper validation` | Vague placeholder for real spec |
| `similar to <X>`, `like <X> but` (without concrete delta) | Refers to undefined precedent |
| `details to follow`, `more details later`, `to be detailed` | Postponed work disguised as commitment |
| `appropriate validation`, `appropriate error message` | "Appropriate" = "I don't know" |
| `lorem ipsum`, `placeholder text` | Fake content |
| `your <X> here`, `<insert X>`, `[X here]` | Template literals leaked |

**Allowed exceptions**:

- Code blocks containing snippets with `// TODO` from existing referenced source — cite path and line, do not introduce new TODOs.
- Risk table cell `accepted (<adr-id>)` — explicit acceptance, not deferred work.

```bash
# Agent runs this (or equivalent) before Phase 5:
grep -nEi "TBD|to be determined|TODO|FIXME|as appropriate|as needed|add error handling|similar to|details to follow|lorem ipsum|placeholder text" docs/features/$ARGUMENTS/PLAN.md
```

A clean PLAN has zero hits. Hits → revise the offending section with concrete content.
If a value is genuinely unknown, the answer is NOT a placeholder — it is either a research
follow-up (escalate back to /arh-research) or an ADR (document the decision in § Architecture decisions).

