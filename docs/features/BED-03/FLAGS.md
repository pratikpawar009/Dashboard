# BED-03 — Agent flags

Appended by `/arh-implement` Step 1 (orchestrator is the single writer; `AF-NN` ids assigned serially here). Triaged by `/arh-human-review BED-03` before commit-PR.

<!-- All four flags triaged 2026-08-27: accepted as-is by the engineer at the Step 1 triage gate. AF-02 promoted to DECISIONS.md D-08, which supersedes D-01's literal `session.begin()` wording while leaving D-01's atomicity guarantee binding. -->

### AF-01: `@app.on_event("shutdown")` is deprecated on this FastAPI version · kind: risky-pattern · task: T-02 · status: triaged-accepted

**Source**: `services/api/app/main.py:22`

`@app.on_event("shutdown")` emits `DeprecationWarning: on_event is deprecated, use lifespan event handlers instead` on the installed FastAPI version (confirmed via `python -W error::DeprecationWarning -c "import app.main"`). Implemented as decided per **D-02**, which explicitly chose `on_event` over a full `lifespan=` refactor this story does not otherwise need. Not silently switched — the decision holds until an engineer revisits it. A future story that adds more startup/shutdown wiring should promote this to `lifespan=` and supersede D-02.

### AF-02: `_rebuild_transaction()` savepoint fallback deviates from D-01's literal `async with session.begin()` · kind: risky-pattern · task: T-03 · status: triaged-accepted

**Source**: `services/api/app/services/rollup_rebuild.py`

D-01 and the T-03 task notes both specify a literal `async with session.begin():` wrapper. A bare `session.begin()` raises `InvalidRequestError: A transaction is already begun` on a second call against a session that has read anything in between — exactly the shape FR-4/D-04's idempotency tests require (rebuild → snapshot via SELECT → rebuild again, same session). T-03 added a private `_rebuild_transaction()` context manager that uses `session.begin()` on a fresh session and falls back to `begin_nested()` (SAVEPOINT) when the session already has an autobegun transaction.

This preserves D-01's guarantee (a mid-rebuild failure rolls back only that call's mutations — verified on both the top-level-begin and savepoint paths) but is a mechanism the plan did not anticipate. Confirm the savepoint path is acceptable, or promote it to a `DECISIONS.md` entry superseding D-01's wording.

### AF-03: `design_check` evidence dimension is N/A — no tool wired · kind: evidence-na · task: evidence-pass · status: triaged-accepted

**Source**: `docs/config/project-commands.yaml`

`design_check:` is empty by design — the file's own comment records that no accessibility / console-error-scan / perf tool has been chosen or installed yet (design provider is `html-mockup`). The evidence pass therefore recorded this dimension as **N/A** rather than PASS. Confirm the N/A is still accepted, or wire a tool (e.g. `axe-playwright` / `pa11y-ci` against `apps/web`) and re-run. BED-03 is a backend-only story, so nothing in this feature would have exercised the dimension regardless.

### AF-04: runtime render check unavailable on the `nextjs` stack · kind: evidence-na · task: evidence-pass · status: triaged-accepted

**Source**: `docs/config/project-commands.yaml` (`test_e2e:` empty)

The runtime dimension asserted boot-clean + HTTP 200 on `/` for `apps/web`, but could not assert the rendered output: no browser-capable E2E runner is installed. The root route is a Server Component, so the 200 response body is server-rendered HTML, but that was not proven with a browser tool this session. Out of scope for BED-03 (backend-only); recorded so the gap is visible rather than implied-covered.


<!-- AF-02 triaged: accepted and promoted to DECISIONS.md D-08. -->
