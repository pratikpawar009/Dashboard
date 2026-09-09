# Feasibility Assessment: ING-02 — POST /api/ingest/files

**Story**: ING-02 — `POST /api/ingest/files` — activity ingest
**Date**: 2026-09-09
**Assessor**: Claude Code

---

## Upstream dependency summary

| Upstream | Contract | State | Availability |
|---|---|---|---|
| ING-01 | `ingest-token-auth` (`docs/requirements/auth.md:67`) | `security-reviewed` | `app/core/ingest_auth.py:45` `get_ingest_token(program_id, credentials, session)` shipped; 401 `missing/unknown/revoked/expired`, 403 `scope`, `"*"` wildcard, empty-list = allow-all |
| BED-01 | `db-schema` (`docs/requirements/data.md:1`) | `review` | `usage_events` model shipped (`app/models/ingestion.py:18`), `uq_usage_events_program_session_cmd_ts` + 5 indexes live in `migrations/versions/001_initial_schema.py` |
| BED-03 | `rollup-rebuild` (`docs/requirements/data.md:86`) | `review` | `rebuild_program_rollups`/`rebuild_org_rollups` shipped (`app/services/rollup_rebuild.py:317,459`), exported on the services barrel |

All three are available and directly callable. No upstream blocks the build. The
blockers found are in the *shape* of what those upstreams do, not their existence.

---

## Exploration Log

- `git status --porcelain` → clean except `docs/activity/activity.jsonl` (unrelated churn). Branch `chore/harness-program-manifest`.
- `/Users/pratik.pawar/.local/bin/uv --version` → `uv 0.9.26`. Postgres reachable: container `dashboard-dev5442`, host port **5442** (`docs/config/stack-smoke.md` says 5432 — known carried-forward defect, confirmed again here).
- `grep -rn "ingest-files-api" docs/` → contract at `docs/requirements/api.md:243`; bound by ING-04, ING-06, ING-09; named in the RTM ING-02 row and 4 story files.
- `grep -rn "ingest/files\|ingest/events" docs/` → `/api/ingest/files` in PRD FR-ING-04 (`docs/prd/ai-sdlc-adoption-dashboards.md:374`), PRD §Journeys (`:220`), PRD §Integrations (`:466`), api.md contract, RTM row, ING-04/06/09 stories. `/ingest/events` appears in **zero** requirement documents.
- Read `docs/requirements/api.md:1-32,243-320`, `docs/requirements/auth.md:67-130`, `docs/requirements/data.md:1-130`.
- Read `app/api/manifest.py` (196 lines, full) — ING-10's sibling endpoint. Read `app/services/manifest_ingest.py:60-400`.
- Read `app/services/rollup_rebuild.py:1-145,317-395,455-490`; `app/models/ingestion.py` (full); `app/core/db.py` (full); `app/main.py` (full); `app/api/ingest.py` (full, 31 lines).
- `grep -rn "UsageEvent" app/ tests/ scripts/ migrations/` → **no production writer exists**. Only `personal_usage.py` and `rollup_rebuild.py` read it; only `tests/` insert. Confirms every token/MAU/command chart renders seeded or empty data today.
- `grep -rn "kind" app/` → **zero reads of `usage_events.kind` anywhere in the application**. The column is write-only-never-read and its vocabulary is defined in no contract.
- `python3` over `docs/activity/activity.jsonl` → 75 rows, `kind` is `"command"` for all 75; outcomes `{completed: 62, error: 13}`; **two distinct key sets** — 1 variant carries extra `source` + `copilot_credits` keys with no `usage_events` column.
- Read `.harness/program.yaml` (full) and `.harness/profile.yaml` (full).
- `grep -rn "statement_timeout\|connect_args\|pool_size" app/` → none. `app/core/db.py:17` is a bare `create_async_engine(settings.database_url)`; `app/services/freshness.py:32` already documents this gap in a comment.
- Read `tests/perf/test_rollup_rebuild_perf.py:1-100` — BED-03-TC-15 asserts `rebuild_program_rollups` ≤ 2.0s at `EVENT_COUNT = 5000`, seeded into an **empty** table. No org-scope perf test exists.
- Read `docs/features/BED-03/DATA-DESIGN.md:53-54`, `DECISIONS.md` D-01/D-05.
- **Measured** (live Postgres :5442, scratch DB `dashboard_test_ing02research`, migrated to head, then dropped): rebuild cost curve, concurrency behaviour, intra-batch duplicate behaviour, bind-parameter ceiling. Results in § Measurements below.
- `python3 docs/design/schema.json` → epics `OVW, PGD, EMD, ARC, DEV, PMD`. **No `ING` epic** → `design: n/a` is legitimate, matching ING-01/ING-10.

### Measurements

Live Postgres, localhost, warm cache, no HTTP layer, no Pydantic validation, no
network latency — i.e. every number below is a **lower bound** on the real endpoint.
Each round upserts one 5000-row batch into `prog-0` and 5000 noise rows into each of
3 other programs, then runs `rebuild_program_rollups("prog-0")` + `rebuild_org_rollups()`.

| total rows | rows in program | upsert 5k (ms) | `rebuild_program` (ms) | `rebuild_org` (ms) | sum (ms) |
|---:|---:|---:|---:|---:|---:|
| 20,000 | 5,000 | 1,829 | 588 | 417 | **2,834** |
| 40,000 | 10,000 | 1,789 | 1,131 | 802 | **3,722** |
| 60,000 | 15,000 | 1,793 | 1,695 | 1,368 | **4,856** |
| 80,000 | 20,000 | 1,800 | 2,197 | 1,671 | **5,668** |
| 100,000 | 25,000 | 1,850 | 2,772 | 2,111 | **6,733** |
| 120,000 | 30,000 | 1,817 | 3,419 | 2,692 | **7,928** |
| 140,000 | 35,000 | 1,864 | 4,117 | 3,829 | **9,810** |
| 160,000 | 40,000 | 1,864 | 4,805 | 3,864 | **10,533** |

Concurrency, 4 simultaneous ING-02-shaped pushes on distinct programs
(`rebuild_program_rollups(pid)` then `rebuild_org_rollups()`, separate sessions):

```
w0 OK
w1 IntegrityError: duplicate key value violates unique constraint "org_summary_rollup_org_id_key"
w2 OK
w3 IntegrityError: duplicate key value violates unique constraint "org_summary_rollup_org_id_key"
```

2 concurrent bare `rebuild_org_rollups()` → 1 OK, 1 `IntegrityError` (same constraint).

Two further hard limits, both reproduced:

- A single `INSERT ... VALUES` of 5000 rows × 22 columns = 110,000 bind parameters →
  `psycopg.OperationalError: number of parameters must be between 0 and 65535`.
  **Max rows per statement for `usage_events` is 2,978.** A 5000-row batch cannot be one statement.
- Two rows sharing `(program_id, session_id, cmd_ts)` *inside one batch* →
  `psycopg.errors.CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect
  row a second time`. This aborts the whole statement, not one row.

### The three commissioned questions

**Q1 — Endpoint path. Canonical is `POST /api/ingest/files`. Not a judgement call: it is
written in six independent places** (PRD FR-ING-04 `:374`, PRD §Journeys `:220`, PRD
§Integrations table `:466`, `docs/requirements/api.md:249`, the RTM ING-02 row, and
ING-04/ING-06/ING-09's ACs). `/ingest/events` exists only in the scaffold stub and is
referenced by no requirement, no contract, and no story. ING-10 already mounted
`APIRouter(prefix="/api/ingest")` in `app/api/manifest.py:97`, so `/files` slots in
beside `/manifest` with no prefix invention.

Recommendation on the stub: **delete `app/api/ingest.py`, do not adopt or rewrite it.**
ING-10's D-02 already ruled on this once for its own endpoint ("its own dedicated router,
never `app/api/ingest.py`'s unregistered stub") and shipped a dedicated module. Rewriting
in place would mean a module named `ingest.py` sitting beside `manifest.py`, both serving
`/api/ingest/*`, with the generic name owned by one specific endpoint. The stub shares
nothing with the real contract — different path, different verb semantics, different
schema, no auth, and a `_persist()` that fabricates a uuid and writes nothing. Two
follow-on consequences the plan must carry, both verified:
- `app/schemas/activity.py` (`ActivityEventIn`/`ActivityEventOut`) has exactly one
  consumer, the stub. Deleting the stub orphans it. It is also cited as the canonical
  in/out-split example in `.claude/skills/pydantic-patterns/SKILL.md`; deleting it
  invalidates those references. Resolve as part of the plan, not silently.
- `app/main.py:78-88`'s 11-line comment explains why the router is unregistered and names
  ING-02 as the story that registers it. It must be replaced, not left dangling.
- `app/core/retry.py`'s `retry_with_backoff` stays — `app/auth/oidc.py:143` and
  `app/auth/jwks.py:202` also use it.

**Q2 — `kind` vocabulary. It is not defined in one place; it is already four vocabularies
sharing one key name, and it will drift.** This is the same failure mode as the roster
role-slug drift, and it is further along:

| # | Where | Values | Meaning | Defined in |
|---|---|---|---|---|
| 1 | `.harness/program.yaml` `files[].kind` | `activity` | which local file to push | a comment in program.yaml |
| 2 | `.harness/program.yaml` `artifacts.<type>.kind` | `glob-count`, `json-key-count`, `json-field-sum`, `constant` | extraction strategy — **totally unrelated vocabulary, same key name** | a comment in program.yaml |
| 3 | Request envelope | `activity` (ING-02), `artifacts` (ING-03) | payload discriminator | split across two api.md contracts (`:249`, `:283`) |
| 4 | `usage_events.kind` column / `activity.jsonl` row `kind` | `command` (all 75 rows) | event type | **nowhere** |

AC-5 says reject "an unrecognized `kind`" without saying which. It cannot mean #4 —
`usage_events.kind` is `nullable=True` (`app/models/ingestion.py:45`), the `db-schema`
contract enumerates no allowed values, and `grep` finds **zero reads of that column
anywhere in `app/`**, so there is no vocabulary to validate against and no consumer that
would notice. Read as #3, AC-5 is also odd: an unrecognized envelope `kind` is a
request-level fact, so it belongs with AC-4's whole-request abort, not in AC-5's
per-row-rejection bucket alongside a malformed date. As written AC-5 is untestable.
This is clarification C-2, and the fix is the `role_map.py` fix: one module owning the
envelope vocabulary that ING-02 and ING-03 both import, so the two endpoints cannot drift.

Adjacent drift found while checking this, worth recording but **not ING-02's to fix**:
ING-04 AC-2/AC-3 (`docs/stories/ING-04.md:23,30`) read `files:`/`artifacts:` off
`.harness/profile.yaml`, but ING-10's canonical-layout decision put both blocks in the
committed `program.yaml` — `profile.yaml` is local, gitignored, and holds only
email/name/role. ING-04 is stale against a decision made after it was written.

**Q3 — Synchronous rollup. The 3s budget is not achievable, and the design needs
revisiting. Two independent reasons, both measured.**

*Reason 1 — the budget is indexed to the wrong variable.* The NFR reads "p95 ≤ 3s for a
5000-row **batch**", derived from BED-03's "≤2s / ≤5000 events" budget. But BED-03's
budget is per **accumulated table**, not per batch: `tests/perf/test_rollup_rebuild_perf.py`
seeds exactly 5000 rows into an empty table and times one rebuild, and BED-03 DECISIONS
D-05 states the ceiling as "5,000 `usage_events` rows per program". Rebuild cost is
O(rows already in the table), and ING-02 is precisely the thing that makes that number
grow. The measured curve is linear and blows the budget on the **second** push
(3.72s at 40k rows) — and it is already at 2.83s, 94% of budget, on the very first push,
with HTTP, JSON parsing and 5000 Pydantic validations still excluded. Note the upsert
alone is a flat ~1.8s, consuming 60% of the budget before any rebuild runs.

*Reason 2 — `rebuild_org_rollups()` is an unbounded fan-out read and a contention point.*
`app/services/rollup_rebuild.py:470` is a bare `select(UsageEvent)` — no `WHERE`, no
`LIMIT` — materialising **every row in the table** as ORM objects into process memory on
every single ingest. That is a direct violation of `.claude/rules/performance-baseline.md`
("No N+1 queries or unbounded fan-out reads. Batch or paginate"). The `rollup-rebuild`
contract's own invariant text says "rebuild cost is O(events for the affected program) per
write" — that is **false for the org half**, and BED-03's `DATA-DESIGN.md:54` says so
plainly ("O(total events)"). The contract text and the shipped design disagree; the
contract is the stale one.

On concurrency, the answer is worse than contention — it is a hard failure, reproduced
above. Every program's ingest rebuilds the same org singleton by `DELETE` + `INSERT` on
`org_summary_rollup` (`unique(org_id)`, `org_id='org-1'`). Under Postgres READ COMMITTED,
two overlapping rebuilds each `DELETE` against their own snapshot and then both `INSERT`,
and the loser dies on `org_summary_rollup_org_id_key`. **2 of 4 concurrent pushes returned
IntegrityError**, which surfaces as a 500. This is not a rare interleaving: the user's
stated architecture is N programs' MCP servers pushing independently, and the window is
the full multi-second rebuild — the wider the table grows, the wider the collision window.
Worse, if the plan follows `manifest_ingest.py`'s precedent and commits the upsert before
rebuilding (`manifest_ingest.py:355`), the losing request leaves `usage_events` committed
with rollups un-rebuilt — a silent partial write behind a 500.

Also on the performance-baseline rule: there is **no I/O timeout anywhere**.
`app/core/db.py:17` is a bare `create_async_engine(settings.database_url)` — no
`connect_args`, no `statement_timeout`, no `pool_timeout`. A 10s rebuild under lock
contention has nothing bounding it. `app/services/freshness.py:32` already flagged this
in a code comment.

---

## Pattern map

### Existing code to extend

- `app/main.py` — add `include_router(ingest_files_router)`; **replace** the 11-line
  comment at `:78-88` that explains why `ingest_router` is unregistered.
- `docs/requirements/api.md#ingest-files-api` — the `shape:` block needs the `rows[]` field
  list added once C-1 is answered; four downstream stories bind to it.
- `docs/requirements/data.md#rollup-rebuild` — its `invariant:` text ("O(events for the
  affected program)") is wrong for the org scope and should be corrected to match
  `docs/features/BED-03/DATA-DESIGN.md:54`. Text-only; no BED-03 code reopens.
- `services/api/README.md` + root `README.md` API table — both document every shipped
  ingest route; ING-10 set that precedent.

### Existing patterns to follow

- **`app/api/manifest.py` is the template, near one-for-one.** Same `APIRouter(prefix="/api/ingest")`;
  same manual `await get_ingest_token(program_id=..., credentials=..., session=db)` call
  rather than `Depends()` — mandatory here for the same reason, because `program_id` travels
  in the **body** and `get_ingest_token`'s `program_id: str` parameter carries no
  `Path`/`Query` annotation, so a declarative `Depends()` would bind it as a required query
  parameter the contract never documents (`app/api/manifest.py` module docstring). Same fresh
  private `HTTPBearer(auto_error=False)` instance (never import `ingest_auth._http_bearer`).
- **Two-tier validation** (`manifest_ingest.py:100-190`): request-level failure aborts with
  zero writes; row-level failure rejects that row only. AC-4 → Tier 1 (413), AC-5 → Tier 2.
  Maps onto ING-02 almost exactly.
- **Row cap at the router, re-checked in the service** (`_TEAM_ENTRY_CAP = 500`, duplicated
  deliberately as defence-in-depth). ING-02's analogue is a 5000 cap.
- **`SectionCounts {received, valid, rejected}`** (`app/schemas/manifest.py`) — extend to
  `received/valid/inserted/updated/rejected` per the contract.
- **Raw-dict body access**, never a whole-body Pydantic bind (`manifest.py` AF-06): binding
  `rows[]` to a model would turn one bad row into a request-wide 422 and break AC-5.
- **`pg_insert(...).on_conflict_do_update(index_elements=[...])`** (`manifest_ingest.py:295`)
  for the idempotent upsert.
- **Named-event structured logging** via a shared emitter function
  (`log_ingest_manifest_write`, promoted from private so router and service share one field
  allowlist) — ING-02's `ingest_write_completed` should follow that shape.
- **`app/core/role_map.py`** — the one-shared-table pattern for a vocabulary two writers must
  not drift on. This is the model for the `kind` fix (C-2).

### New files to create (best-guess)

- `services/api/app/api/ingest_files.py` — router, `POST /api/ingest/files`.
- `services/api/app/services/activity_ingest.py` — validate + chunked upsert + rebuild.
- `services/api/app/schemas/ingest_files.py` — `ActivityRowIn`, `IngestFilesResponse`.
- `services/api/app/core/ingest_kind.py` (or equivalent) — the single envelope-`kind`
  vocabulary, imported by ING-02 and ING-03. Pending C-2.
- `services/api/tests/unit/test_activity_ingest.py`, `test_ingest_files_auth_scope.py`,
  `test_ingest_files_idempotency.py`
- `services/api/tests/perf/test_ingest_files_perf.py` — must seed a **pre-populated** table,
  not an empty one, or it repeats BED-03-TC-15's blind spot.
- **Deleted**: `services/api/app/api/ingest.py`; probably `app/schemas/activity.py`.

### Shared code at risk

| Module | Why it ripples |
|---|---|
| `app/services/rollup_rebuild.py:470` | The unfiltered `select(UsageEvent)`. Any fix to Q3 touches BED-03's shipped code — and RTM's standing decision is "no validated story reopens". Highest-tension point in the story. |
| `app/core/db.py:17` | Adding a `statement_timeout` changes every DB caller in the app, not just ingest. |
| `app/main.py:78-88` | Router registration + the stub comment; every app instance and every test using `create_app()`. |
| `app/schemas/activity.py` | Orphaned by the stub deletion; cited by `pydantic-patterns` SKILL.md. |
| `docs/requirements/api.md#ingest-files-api` | ING-04, ING-06, ING-09 bind to it. Any `rows[]` shape decided here is expensive to change later. |
| `app/core/ingest_auth.py` | Consumed, not modified — but ING-02 becomes its second caller, so its `program_id`-as-parameter convention gets locked in. |
| `org_summary_rollup`, `token_series`, `mau_series` | Org singletons every program's ingest rewrites. The contention surface. |

### Call path

```
POST /api/ingest/files  {program_id, kind:"activity", rows[<=5000]}
   |
   +-- request.json()  (raw dict, never a whole-body model bind)   -- AC-5
   +-- get_ingest_token(program_id, credentials, session)          -- AC-2 (401) / AC-3 (403)
   +-- len(rows) > 5000 -> 413, zero writes                        -- AC-4
   |
   +-- per-row ActivityRowIn.model_validate()  -> valid[] / rejected[]   -- AC-5
   +-- chunked pg_insert(...).on_conflict_do_update()   <= 2978 rows/stmt -- AC-1, AC-6
   |        ^ measured hard limit: 22 cols x 2978 = 65,516 bind params
   +-- rebuild_program_rollups(session, program_id)     O(rows in program)
   +-- rebuild_org_rollups(session)                     O(ALL rows)  <-- unbounded
   |                                                    <-- org singleton, collides
   +-- log ingest_write_completed ; return counts + rollup summaries
```

---

## Risk register

| # | Dimension | Severity | Description | Mitigation |
|---|---|---|---|---|
| 1 | Performance | **CRITICAL** | Measured 2.83s at the first 5000-row push (94% of the 3s budget) and 3.72s at the second, 10.5s by the eighth — excluding HTTP, JSON parsing and 5000 Pydantic validations. The NFR is indexed to batch size but the cost is driven by accumulated table size. | Re-index the NFR to table size and re-baseline. Then one of: (a) push both rebuilds out of the request onto a background task / queue and return `202` with the counts, revising AC-1; (b) keep `rebuild_program_rollups` synchronous (cheap while a program is small) and debounce/coalesce `rebuild_org_rollups` out-of-band; (c) replace both Python-side full scans with SQL aggregate `INSERT ... SELECT`. (b) is the smallest change that gets under budget. Blocked on C-3. |
| 2 | Integration | **CRITICAL** | Concurrent pushes from different programs fail: **2 of 4** returned `IntegrityError` on `org_summary_rollup_org_id_key`, reproduced live. Every ingest DELETE+INSERTs the same org singleton. Surfaces as a 500, and if the upsert is committed first (the `manifest_ingest.py:355` precedent), `usage_events` is committed with rollups un-rebuilt behind that 500. | Serialise the org rebuild: a Postgres advisory lock (`pg_advisory_xact_lock`) around `rebuild_org_rollups`, or `ON CONFLICT DO UPDATE` on the org singleton instead of DELETE+INSERT, or move it out of the request path per risk #1's mitigation (b), which also removes this. Separately: define the commit boundary explicitly — either one transaction spanning upsert+rebuild, or a documented, tested partial-failure response. |
| 3 | Performance | **HIGH** | `rollup_rebuild.py:470`'s bare `select(UsageEvent)` is an unbounded fan-out read (whole table into process memory, as ORM objects) — a direct `.claude/rules/performance-baseline.md` violation, and a memory-growth risk independent of latency. | Same as #1(c): rewrite as a SQL aggregate so no row set is materialised, or bound the scan by the ranges the org rollups actually need (`token_series`/`mau_series` are per-month; `org_summary_rollup` needs distinct-program counts and sums — all expressible as `GROUP BY` without loading rows). Touches BED-03; see risk #6. |
| 4 | Domain | **HIGH** | A 5000-row batch **cannot** be one INSERT: 22 columns × 5000 = 110,000 bind parameters vs Postgres' 65,535 ceiling (reproduced: `psycopg.OperationalError`). Max 2,978 rows/statement. ING-10's 500-entry cap never hit this, so the precedent does not cover it. | Chunk the upsert at a named constant ≤ 2,978 (1,000 is a round, safe value and was what the measurement used), inside one transaction. Assert the ceiling in a test so a future column addition to `usage_events` cannot silently break it. |
| 5 | Domain | **HIGH** | Two rows sharing `(program_id, session_id, cmd_ts)` **inside one batch** raise `CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect row a second time` — which aborts the whole statement, not one row. AC-5 assumes every row-level problem is a per-row rejection; this one is not, and a real `activity.jsonl` re-read after an append can plausibly contain it. | De-duplicate on the composite key in Python before the upsert (last-wins, matching upsert semantics), counting the dropped rows into `rejected` with a distinct reason. Add it to AC-5's rejection-reason enumeration. Cover with a test. |
| 6 | Dependency | **HIGH** | Every credible fix to risks #1/#2/#3 modifies `app/services/rollup_rebuild.py`, which is BED-03 — `validated`, shipped, `phase: review`. RTM's standing decision (2026-09-08) is explicitly "**no validated story reopens**", the reasoning that forced ING-10 to create `program_roster` rather than touch `program_members`. | Decide the ownership question before planning: either ING-02 is granted an explicit, recorded exception to modify `rollup_rebuild.py`, or a new BED story is cut to own the rebuild-scaling change and ING-02 depends on it. Do not let the plan quietly edit a validated story's module. Part of C-3. |
| 7 | Domain | **MED** | The `rows[]` wire schema is specified nowhere. `activity.jsonl` uses `duration_s`, `input_token`, `output_token`, `cache_read`, `cache_write`; `usage_events` uses `duration_seconds`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`. Rows carry no `program_id`. One of the two observed key sets carries `source` + `copilot_credits` with no column — Pydantic's default would silently drop them. Four stories bind to this contract. | C-1. Resolve, then write the field list (including the unknown-field policy: ignore vs reject) into `api.md#ingest-files-api` before ING-04/06/09 plan against it. |
| 8 | Domain | **MED** | `kind` is four vocabularies sharing one key name (see Q2). AC-5's "unrecognized `kind`" is ambiguous and, read against `usage_events.kind`, untestable — the column is nullable, unconstrained, and read by nothing. | C-2. Define the envelope vocabulary in one module shared with ING-03, on the `app/core/role_map.py` model. Reclassify the envelope-`kind` check as a request-level abort (AC-4's tier), or state explicitly that AC-5 governs the row-level column and give that column a vocabulary. |
| 9 | Performance | **MED** | No I/O timeout exists anywhere: `app/core/db.py:17` is a bare `create_async_engine(...)` — no `connect_args`, no `statement_timeout`, no `pool_timeout`. `.claude/rules/performance-baseline.md` requires explicit timeouts. A multi-second rebuild under lock contention is unbounded. | Set a `statement_timeout` via `connect_args` scoped to the ingest path, or app-wide with a documented value. App-wide changes every caller — call it out in the plan rather than slipping it in. |
| 10 | Compatibility | **MED** | Deleting `app/api/ingest.py` orphans `app/schemas/activity.py` (its only consumer) and invalidates the `pydantic-patterns` SKILL.md references that cite it as the canonical in/out-split example. | Decide delete-vs-keep for the schema module explicitly in the plan; if deleted, update `.claude/skills/pydantic-patterns/SKILL.md`'s Examples and References to a live module. Zero runtime compat risk — `/ingest/events` is a 404 today, so no client can break. |
| 11 | Security | **MED** | Activity rows are "confidential individual-activity detail" per the story's Security NFR. Per-row rejection reasons and the `ingest_write_completed` event must not leak `user` (an email), `command`, or `feature`. ING-10 hit this and added `test_manifest_pii_logging.py`. | Mirror ING-10: a fixed field allowlist on the log event (counts + `program_id` + `duration_ms` only), rejection reasons carry a row **index** and a reason code, never row content. Add the equivalent PII-logging test. |
| 12 | Domain | **LOW** | AC-6's "rebuilt rollup rows are identical" is true only of business-value columns — BED-03 D-04 regenerates `id`, `as_of_timestamp`, `created_at`/`updated_at` on every rebuild by design. | Not a defect; state the comparison basis in the test so AC-6 does not fail on regenerated ids. BED-03's own idempotency tests already establish the pattern. |
| 13 | Integration | **LOW** | `ingest_tokens.last_used_at` exists but nothing observed updates it; ING-02 doubles ingest traffic and would make the gap more visible. | Out of scope. Record as carry-forward; ING-01 owns the token lifecycle. |

---

## Score

| Dimension | Weight | Score | Reasoning |
|---|---:|---:|---|
| Integration | 25 | 68 | Upstreams shipped and directly reusable; `app/api/manifest.py` is a near one-for-one template. Docked hard for a *demonstrated* failure mode: concurrent pushes 500 on the org singleton (2 of 4), with an undefined commit boundary behind it. |
| Compatibility | 20 | 78 | No runtime compat risk — `/ingest/events` is already a 404, no client exists. Downstream consumers are all unbuilt so the contract is still settable. Docked for the unspecified `rows[]` shape that 4 stories bind to, and the stub-deletion ripple into `pydantic-patterns`. |
| Domain | 20 | 62 | Four invariants the story does not enumerate surfaced during the scan, two of them reproduced as hard errors (65,535 bind-parameter ceiling; intra-batch `CardinalityViolation`). The `kind` collision makes AC-5 untestable as written. |
| Performance | 15 | **30** | Budget exists but is demonstrably unmeetable and indexed to the wrong variable: 2.83s at the first push, 3.72s at the second, 10.5s by the eighth — before HTTP and validation. Two `performance-baseline.md` violations (unbounded fan-out read; no I/O timeout). |
| Dependency | 20 | 82 | All three upstreams complete, nothing external blocks. Docked because every credible perf fix modifies BED-03's shipped `rollup_rebuild.py`, against a standing "no validated story reopens" decision. |

**Total: 66/100 → SPIKE**

Two independent triggers land on the same verdict: the weighted total falls in the
60–69 SPIKE band, and Performance at 30 is below the automatic-SPIKE floor of 40.

---

## Spike scope (what to retire before re-running research)

Small and bounded — a day's work, not a redesign. The measurements above already did the
diagnosis; the spike is to pick and prove the fix.

1. **Prototype the org-rebuild fix and re-measure.** Try, in order of increasing cost:
   `pg_advisory_xact_lock` around `rebuild_org_rollups` (fixes the 500s, not the latency);
   moving the org rebuild off the request path (fixes both); rewriting both rebuilds as
   SQL `INSERT ... SELECT ... GROUP BY` (fixes both plus the unbounded read). Re-run the
   cost curve at 20k/100k/500k rows and the 4-way concurrency test against each.
2. **Settle the BED-03 ownership question** (risk #6) — explicit exception for ING-02, or a
   new story. This is a decision, not an experiment, but it gates the plan.
3. **Answer C-1, C-2, C-3** below and write C-1's field list into
   `docs/requirements/api.md#ingest-files-api` before ING-04/06/09 plan against it.

Everything else (chunking, intra-batch dedup, PII logging, stub deletion, timeouts) is
ordinary planning work and needs no spike — the mitigations are already concrete.

---

## Synthesis

**SPIKE.** ING-02 is the right story and its build surface is unusually well-prepared —
ING-10's `app/api/manifest.py` and `app/services/manifest_ingest.py` are a near one-for-one
template for AC-1 through AC-5, all three upstream contracts are shipped and callable, and
the endpoint path is unambiguous (`POST /api/ingest/files`, corroborated in six places;
the `/ingest/events` stub is scaffold residue referenced by no requirement and should be
deleted). What blocks it is AC-1's synchronous-rollup requirement, and the evidence is
measured, not inferred: against the live dev Postgres a 5000-row push costs 2.83s at the
smallest realistic table size — 94% of the 3s budget with HTTP, JSON parsing and 5000
Pydantic validations still excluded — 3.72s on the second push, and 10.5s by the eighth,
because `rebuild_org_rollups()` (`app/services/rollup_rebuild.py:470`) is an unfiltered
`select(UsageEvent)` whose cost tracks total accumulated rows, not batch size. The single
biggest risk is not latency but correctness under the exact architecture this is being
built for: with N programs pushing independently, every ingest DELETE+INSERTs the same
`org_summary_rollup` singleton, and **2 of 4 concurrent pushes died on
`org_summary_rollup_org_id_key`** — a 500 that, following ING-10's commit-then-rebuild
precedent, would leave `usage_events` written and rollups stale. Next step: run the bounded
spike above — serialise or relocate the org rebuild, re-measure, and get a decision on
whether ING-02 may modify BED-03's shipped `rollup_rebuild.py` — then answer the three
clarifications and re-run `/arh-research ING-02`.

---

## Recommendations for planning

1. **Re-index the NFR to accumulated table size, not batch size.** "p95 ≤ 3s for a 5000-row
   batch" is unfalsifiable without stating the table size it holds at. State both.
2. **Do not put `rebuild_org_rollups()` in the request path.** It is the single cause of
   both the latency curve and the concurrency 500s. `rebuild_program_rollups` is defensible
   synchronously while programs are small; the org rebuild is not, at any size.
3. **Delete `app/api/ingest.py`; create `app/api/ingest_files.py`** with
   `prefix="/api/ingest"`, mirroring `app/api/manifest.py`. Replace `app/main.py:78-88`'s
   comment. Decide `app/schemas/activity.py`'s fate explicitly.
4. **Copy `app/api/manifest.py`'s auth wiring verbatim in shape** — manual
   `await get_ingest_token(...)`, not `Depends()`, because `program_id` is in the body.
   This is not a style choice; `Depends()` would add an undocumented required query param.
5. **Chunk the upsert at a named constant ≤ 2,978** and assert the bind-parameter ceiling
   in a test, so adding a column to `usage_events` later cannot silently break it.
6. **De-duplicate the batch on `(program_id, session_id, cmd_ts)` in Python before the
   upsert**, with a distinct rejection reason. Add it to AC-5's enumeration.
7. **Give the envelope `kind` one owning module** shared with ING-03, on the
   `app/core/role_map.py` model — that module exists precisely because this vocabulary
   drift already happened once here.
8. **Write the `rows[]` field list into `api.md#ingest-files-api`** — including the
   unknown-field policy — before ING-04/06/09 plan against it.
9. **Mirror ING-10's PII-logging discipline**: fixed field allowlist on
   `ingest_write_completed`, row indices in rejection reasons, never row content, plus the
   equivalent of `test_manifest_pii_logging.py`.
10. **Seed the perf test against a pre-populated table.** `tests/perf/test_rollup_rebuild_perf.py`
    tests an empty one, which is exactly why this cost curve was not caught at BED-03.
11. **Correct `data.md#rollup-rebuild`'s invariant text** — "O(events for the affected
    program)" is false for the org scope, per BED-03's own `DATA-DESIGN.md:54`. Text only.
12. **Carry forward** (do not fix here): `docs/config/stack-smoke.md` says port 5432, the dev
    container is 5442; ING-04's ACs read `files:`/`artifacts:` from `profile.yaml` but
    ING-10 moved both to `program.yaml`; `ingest_tokens.last_used_at` is never updated.

---

## Clarifications

**None open.** All three markers resolved in clarify round 1
(`docs/features/ING-02/clarify-1.md`, answered 2026-09-09 by Pratik Pawar).

### Resolved clarifications

- **C-1 — `rows[]` wire shape** → *Persist everything.* Producer POSTs raw `activity.jsonl` field
  names; the API aliases the five that differ (`duration_s`/`input_token`/`output_token`/
  `cache_read`/`cache_write`). `source` and `copilot_credits` are **stored, not dropped** — which
  requires an **additive migration** on `usage_events` (ING-10's `003_program_roster` pattern:
  additive only, existing columns and behaviour untouched). An unknown field must not be silently
  discarded.
- **C-2 — which `kind`** → *Envelope only.* The envelope `kind` (`activity`/`artifacts`) is a
  request-level fact and belongs in **AC-4's whole-request abort tier**. The per-row
  `usage_events.kind` is stored verbatim, unvalidated — all 77 rows in the current activity log
  carry `kind: "command"` and nothing in `app/` reads the column. **AC-5 must be reworded** to drop
  its "unrecognized `kind`" clause; its other cases stand.
- **C-3 — synchronous rollup / BED-03 ownership** → *A new story owns the rollup fix; ING-02
  depends on it.* ING-02 does **not** edit `rollup_rebuild.py`; the standing "no validated story
  reopens" rule holds. The new story owns the org-singleton concurrency failure, the unbounded
  whole-table `select(UsageEvent)` (`rollup_rebuild.py:470`), and the rebuild cost scaling with
  table size rather than batch size. ING-02 is **blocked** on it, and the p95 NFR cannot be
  re-baselined until it lands.

> Re-score note: these answers move both CRITICAL risks out of ING-02's own scope and into an
> upstream dependency. The Performance dimension (30/100) was scored against ING-02 owning the
> fix. A re-run of `/arh-research ING-02` — after the new rollup story exists — should re-score
> Performance and Dependency against the resolved shape.

---

## State write

```json
{
  "research": "complete",
  "research_verdict": "SPIKE",
  "phase": "research",
  "last_updated": "2026-09-09T07:05:56Z"
}
```
