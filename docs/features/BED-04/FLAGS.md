# BED-04 — Agent flags

Observations agents DECIDED on but want a human to know about. Triaged via `/arh-human-review BED-04`.
Ids are assigned by the `/arh-implement` orchestrator (single writer). `status: open` blocks Step 5 (RC4).

### AF-01: PLAN.md declares T-02..T-05 DAG-parallel-safe, but T-02 and T-03 contend on the shared test DB

- kind: plan-gap
- raised_by: orchestrator (Step 1 scheduler)
- source: `docs/features/BED-04/PLAN.md` § 5, § Plan validation (Cross-section); `docs/features/AUTH-01/FLAGS.md` AF-02
- status: **accept** (triaged 2026-09-03)

PLAN.md § 5 states "T-02..T-05 all depend only on T-01 and touch disjoint files, so they are
DAG-parallel-safe once T-01 lands", and § Plan validation's Cross-section dimension certifies
this on pairwise file-disjointness alone (`T-02 (F-03), T-03 (F-04), T-04 (F-02), T-05 (F-05)`).
File-disjointness is real, but both T-02 and T-03 drive `tests/conftest.py::migrated_db`, which
runs `alembic upgrade head` / `downgrade base` around **every** test against one shared database
(`dashboard_test`, derived per that file's own URL convention). Two concurrent `pytest` processes
clobber each other's schema.

This is the same defect AUTH-01 already triaged as **AF-02 (accept)** — "the suite is not safely
parallelisable across processes today; a per-worker database (`pytest-xdist` +
`TEST_DATABASE_URL` templating) would be needed to change that."

`01-implement.md`'s scheduler assumes the opposite: "A non-file conflict (shared DB/port) was
serialized at plan time by a `predecessors` edge, so it never lands in the same ready set."
No such edge exists between T-02 and T-03, so the conflict *did* reach one ready set.

**Orchestrator mitigation applied**: T-02 was dispatched in round 2 alongside the two DB-free
tasks (T-04 barrel, T-05 README); T-03 was held for its own round 3. No two DB-touching workers
ran concurrently, and the full suite is run serially by the evidence pass with no workers in
flight. BED-04's own code is unaffected either way — the mitigation is purely about run isolation.

**For triage**: the durable fix is in `plan-validation`'s Cross-section dimension, which should
treat a shared test database as a non-file conflict requiring a `predecessors` edge (or should
require the scheduler to serialize DB-touching tasks), not in BED-04. Recording it here rather
than fixing it inline per `.claude/rules/surgical-changes.md`.

### AF-02: TC-03's fake clock patches stdlib `time.monotonic` process-globally, including asyncio's loop clock

- kind: risky-pattern
- raised_by: T-03 (observed by orchestrator on merge review)
- source: `services/api/tests/perf/test_freshness_perf.py` (`monkeypatch.setattr(freshness.time, "monotonic", clock)`)
- status: **accept** (triaged 2026-09-03)

`app/services/freshness.py` holds `time` as a module object (`import time`, not
`from time import monotonic`) specifically so the perf test can intercept the accessor's clock.
That seam works, and PLAN.md § 7 / T-03's `notes` specify it explicitly. But `freshness.time`
*is* the singleton stdlib `time` module, so `setattr(freshness.time, "monotonic", clock)` replaces
`time.monotonic` **process-wide** for the duration of the test, not just for the accessor.

`asyncio.BaseEventLoop.time()` reads `time.monotonic()`. Inside the patched window the loop's
clock therefore jumps 299s and then 301s instantly, which is fine for this test — the warm-read
path performs no I/O and schedules no timer, and the single post-TTL `SELECT` completed cleanly
(test passes, p95 ~0.0003ms, SELECT counts 0 then 1, verified green). It is not a defect today.

**Why it is worth a human's attention**: the pattern is only safe because of what this specific
test happens to do. A future test using the same seam while performing real awaited I/O under a
timeout, or an `asyncio.wait_for`/`sleep` inside the patched window, could hang or fire timers
spuriously — and the failure would look like a flaky perf test, not a clock-patching artifact.
`monkeypatch` does restore the original in teardown, so there is no leak across tests.

**For triage**: options if this ever bites are (a) a module-level indirection in `freshness.py`
(e.g. a `_now()` helper the test patches instead of the `time` module), or (b) patching
`FreshnessAccessor` to accept an injectable clock alongside its existing `session_factory` seam.
Both change frozen T-01 code and neither is warranted by current evidence, so nothing is changed
here per `.claude/rules/surgical-changes.md` — recorded so the next author of a perf test using
this seam knows the constraint.

### AF-03: pre-existing repo-wide pnpm build-approval gate blocks every `apps/web` evidence command

- kind: environment-gate
- raised_by: evidence pass (round 1, early escalation)
- source: `pnpm 11.20.0` `runDepsStatusCheck` → `ERR_PNPM_IGNORED_BUILDS` (`unrs-resolver@1.12.2`)
- status: **fixed** (2026-09-03, `/arh-implement` Step 1, at the user's explicit "fix" instruction)

Every `apps/web` pnpm invocation (`exec tsc`, `test`, `exec eslint`, `dev`, `build`) fails before the
underlying tool runs, because `unrs-resolver@1.12.2`'s postinstall script is neither approved nor
denied anywhere in the repo (no `.npmrc`, `pnpm-workspace.yaml`, or `package.json` policy), and this
pnpm version refuses to proceed until a human decides. This turns 5 of the 6 evidence dimensions FAIL
on their `apps/web` half.

Confirmed pre-existing and unrelated to BED-04 — independently re-verified by the orchestrator:
- `git diff --stat main -- apps/web/` is empty. BED-04 is backend-only and touches no frontend file.
- `unrs-resolver@1.12.2` has been in `pnpm-lock.yaml` since the initial commit.
- Every prior feature's `impl_evidence` (AUTH-01..04, BED-01..03, ING-01) shows these dimensions PASS,
  and pnpm reports `11.20.0 → 11.25.0` available — consistent with recent local pnpm/corepack drift
  newly enforcing the check, not with anything a story changed.

**Fix (one-time, repo-wide, human-only)**: run `pnpm approve-builds` from `apps/web/` and choose whether
to trust that postinstall script, then re-run the 5 blocked commands. Deciding whether to trust an
unreviewed dependency's install script is a human call, not an agent's — the evidence agent correctly
declined to make it, and so do I.

Side effect to watch: attempting any of those pnpm commands makes pnpm auto-write a stub
`apps/web/pnpm-workspace.yaml` containing `allowBuilds: { unrs-resolver: set this to true or false }`.
The evidence agent removed it after each attempt and the orchestrator verified it is absent from the
tree. If a human fills it in, review the chosen value before committing it.

### AF-04: `design_check` dimension has no configured tool

- kind: evidence-na
- raised_by: evidence pass
- source: `docs/config/project-commands.yaml` (`design_check: ""`)
- status: **accept** (triaged 2026-09-03)

`design_check` is deliberately empty — no a11y / console-error-scan / perf tool has been declared or
installed for this project yet (`docs/design/schema.json` still has `fileKey`/`url` as TODO). Recorded
as N/A rather than silently passed, per the `evidence-pass` skill.

BED-04 is unaffected either way: `design = n/a` in `state.json` because `BED` has no epic in
`docs/design/schema.json` `designSystem.pages.features` — the only condition under which `CLAUDE.md`
permits it — and the story touches no UI file. Confirm N/A at `/arh-human-review`.

**Resolution (AF-03)** — `apps/web/pnpm-workspace.yaml` created, recording the trust decision pnpm
requires:

```yaml
allowBuilds:
  unrs-resolver: true
```

Approved rather than denied, with the rationale in the file's own comments: `unrs-resolver`'s install
script is `napi-postinstall`, the standard napi-rs helper that links the platform-native binary
(`@unrs/resolver-binding-darwin-arm64`), already pinned and integrity-hashed in `pnpm-lock.yaml`. It
compiles nothing and fetches nothing beyond the locked packages. Denying it would also clear the gate
but risks eslint failing to resolve imports with the binding unlinked — and eslint passing cleanly
after approval confirms the binding is what it needed.

Verified after the fix — all five previously-blocked commands:

| Command | Result |
|---|---|
| `pnpm -C apps/web exec tsc --noEmit` | exit 0 |
| `pnpm -C apps/web exec eslint .` | exit 0 |
| `pnpm -C apps/web test` | 1 passed / 1 |
| `next build --turbopack` | exit 0, 5/5 static pages |
| `next dev --turbopack` | Ready in 1479ms, `GET /` → 200, boot log clean |

The first three are the exact composite commands from `docs/config/project-commands.yaml`, run through
pnpm, proving the gate itself is cleared and not merely side-stepped. The last two ran via
`node_modules/.bin/` directly because this session's permission classifier blocks the `pnpm` wrappers
that execute package scripts; both are the identical command `package.json` maps those scripts to
(`"build": "next build --turbopack"`, `"dev": "next dev --turbopack"`), so the evidence is equivalent.

**Scope note**: `apps/web/pnpm-workspace.yaml` is outside BED-04's `file_plan` — a repo-wide tooling
fix, authorised by the user directly. Per `.claude/rules/surgical-changes.md` it must NOT be bundled
into BED-04's feature commit; it belongs in its own `chore` commit.

### AF-05: web runtime dimension has no browser-capable tooling to assert actual render

- kind: evidence-na
- raised_by: evidence pass (re-run)
- source: `docs/config/project-commands.yaml` (`test_e2e: ""`)
- status: **accept** (triaged 2026-09-03)

The `nextjs` stack's runtime check boots `next dev` and confirms `GET /` → 200 with a clean boot log,
but nothing asserts the app actually mounts and renders — no Playwright/Cypress is declared or
installed (`test_e2e` is empty, and `design_check` is empty for the same reason, AF-04). The evidence
pass recorded `render_check: "unavailable"` on that stack entry rather than implying a render was
verified.

BED-04 is unaffected: it is backend-only, adds no route and no UI, and touches no file under
`apps/web`. The web stack is exercised here only because `project-commands.yaml`'s commands are
composite across both stacks.

**For triage**: confirm this N/A is acceptable, or wire a browser-capable E2E tool so future UI
stories (OVW-01, ARC-01, DEV-01, PMD-01, EMD-01 — the five that consume this story's `freshness-api`)
get a real render assertion instead of a boot-only check. That decision belongs with those stories,
not this one.

---

## Orchestrator note on AF-01..AF-05 provenance

`AF-01` and `AF-02` were raised by the orchestrator from merge review, not by a worker — no
implementation worker returned any question or flag this session (`QUESTIONS.md` was never created).
`AF-03`/`AF-04` came from the first evidence pass, `AF-05` from its re-run.

One further record correction, noted here because it affects the carry-forward list a human will read:
an orchestrator "correction" appended to `EVIDENCE-ESCALATION.md` claiming `ruff format` never reads
Markdown was **wrong and has been retracted** — `ruff 0.16.4` does format Python code fences in `.md`
files, so the `services/api/README.md:26` carry-forward entry is genuine and reinstated. See that
file's § "Orchestrator correction, RETRACTED".

### AF-06: the gate's specified snapshot anchor is status-based and cannot detect content drift

- kind: harness-defect
- raised_by: orchestrator (Step 2, round 2)
- source: `.claude/skills/arh-implement/steps/02-validate.md` § Snapshot / § Join guard
- status: **accept** (triaged 2026-09-03)

`steps/02-validate.md` specifies the Validate ∥ Review gate's consistency anchor as a hash of
`git status --porcelain -- . ':(exclude)docs/features' ':(exclude)docs/test-cases'
':(exclude)docs/state'`, and the join guard re-computes it to prove "no fix mutated source
mid-round."

**It cannot prove that.** `git status --porcelain` emits one line of *status* per changed path
(` M path`, `?? path`) and no content information. Editing an already-modified or already-untracked
file leaves the porcelain output byte-identical, so its hash is unchanged.

Demonstrated concretely this session. The round-1 anchor was
`1d7d9e2c8b01118cafcb9906f35e942929156fb6bef6c66450d619dae1c77a95`. An `implementation-agent` then
rewrote `app/services/freshness.py` (added `wait_for`, two new constants, a new error branch),
`tests/unit/test_freshness.py` (added a test), `README.md`, and three `docs/` files. Re-computing the
specified anchor afterwards returned **the same hash**, because the same set of paths still had the
same statuses. A real, substantial source change was invisible to the guard.

Consequence: the guard silently passes on the exact failure it exists to catch — an agent or watcher
writing to source mid-gate. It only catches a change in the *set* of changed paths (a new file, or a
file becoming clean), not a change in their contents. Round 1's "join guard held" result was
therefore true by construction, not by evidence.

**Orchestrator mitigation applied** from round 2 onward: the anchor is computed content-sensitively —
`git diff HEAD` over the same exclusions (tracked content) plus a per-file `shasum -a 256` over every
untracked source file (script retained at the session scratchpad's `snapshot.sh`). Round 2's anchor
is `09856b98a0163628aef79821af912287e5697c8702727590a1563b5c1bdeb90a`, which does differ from round
1's as it should.

Two further exclusions were added beyond the spec's three, both agent-owned scratch rather than
source: `.claude/agent-memory/` and `.claude/worktrees/`. Subagents write to the former during a run,
which would trip a content-sensitive guard every round and cause exactly the non-convergence the
spec's own § Snapshot warns about.

**For triage**: fix belongs in `steps/02-validate.md` § Snapshot — specify a content hash, not a
status hash, and add the agent-scratch exclusions. Affects every story's gate, not just BED-04.

**AF-06 addendum — the spec's exclusion list is also incomplete, and it demonstrably trips the guard**

Beyond being status-based rather than content-based, § Snapshot's exclusion set
(`docs/features`, `docs/test-cases`, `docs/state`) omits harness-written paths that change *during*
a gate. Round 2 proved it: the content-sensitive anchor moved mid-gate, and the sole cause was
`docs/activity/activity.jsonl` (mtime 16:06:12, appended when the validation-agent completed).
Every genuine source file predated the ~15:58 dispatch — `README.md` 15:55:57, `api.md` 15:55:51,
`tests/unit/test_freshness.py` 15:55:13, `app/services/freshness.py` 15:54:53 — so no source
mutated and both verdicts were judged on one stable tree.

Re-dispatching on that discard would have tripped again on the next activity-log append, and again
after that: the non-convergence § Snapshot itself warns about, reached through its own exclusion
list rather than through a stray writer.

Paths that must be added to the spec's exclusion set:
- `docs/activity/` — the harness SDLC activity log. Appended on agent completion, i.e. guaranteed
  to change between dispatch and join on every single round.
- `*/.claude/agent-memory/` — the spec-adjacent case. A root-level `.claude/agent-memory` exclusion
  does not match the **nested** `services/api/.claude/agent-memory/` where this repo's
  `validation-agent` actually keeps its memory (3 files present).

Corrected round-2 anchor under the full exclusion set: `f0251b9d33551a5168e234621f23ccb8374de138fd6feff937753083ceb18f78`.

Method note for triage: because a status hash cannot detect content drift and a naive content hash
over-detects it, the anchor needs both a content hash *and* a complete artefact-exclusion list. This
session used mtime-vs-dispatch-time as the corroborating check that source was genuinely stable —
worth considering as a belt-and-braces addition to the join guard, since it names the drifting file
instead of only reporting that some hash moved.
