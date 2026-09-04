# Code Review — feature/AUTH-05

- Date: 2026-09-04T09:33:48Z
- Mode: current (GATE MODE — report-only, invoked from `/arh-implement` Validate ∥ Review gate)
- Files reviewed: 23 (12 tracked modified + 11 new source/test files under `apps/web`; doc/state artefacts excluded from the count, reviewed for contract/ADR consistency only)
- Verdict: **PASS**

## Executive summary

AUTH-05 ships the frontend session/token layer exactly as ADR-0008/DECISIONS.md D-08–D-11 specify: an httpOnly `dashboard_session` cookie owned by `tokenStore.ts`, `/login`+`/callback` relay Route Handlers, two full request-proxy Route Handlers (`/api/proxy/programs`, `/api/proxy/program-detail/[program_id]`), and a clean `programDetailApi.ts` (server) / `programDetailApi.client.ts` (client) module split. Every file touched maps to a `tasks.json` `file_plan` entry (F-01..F-21); `services/api`'s only footprint is the documented `.env.example` config-value change (F-01) — no Python code changed, honoring the hard constraint. `docs/requirements/auth.md`'s `session` contract was updated in the same diff to add AUTH-05 as a second `produced_by`, so there is no contract-drift.

🟢 **Strengths**: the ADR-0008 token-containment boundary is real, not just documented — verified by grep (`ProgramDetailView.tsx`/`programDetailApi.client.ts` import neither `tokenStore` nor `next/headers`) and by a dedicated structural test (`ProgramDetailView.authFlow.test.tsx`'s "structural check" case) that greps the actual shipped source, not a mock. `tokenStore.callWithAuth`'s retry-once and the single-flight `refreshPromise` guard are correct (finally-cleared on both paths, verified by a concurrent-caller test asserting exactly one `POST /auth/refresh`). Every new outbound `fetch` (login, callback, refresh, both proxies) carries an explicit `AbortSignal.timeout(5000)`. `tokenStore.security.test.ts` is a genuinely rigorous no-token-leak audit — it spies all six console methods, serializes logged objects (not just strings), and runs every failure branch of `tokenStore`/`login`/`callback` including error bodies engineered to contain a JWT-shaped string. AF-01/AF-02/AF-03 (already-triaged) were not re-litigated.

⚠️ **Warnings**: one MEDIUM (a documented-vs-actual behavior mismatch in `tokenStore.ts`'s cookie-mutation error handling) and one LOW (an out-of-scope diff line in `docs/activity/activity.jsonl`). Neither blocks.

🛑 **Blockers**: none.

## Findings summary

| Severity | Count | Category distribution                  |
|----------|-------|------------------------------------------|
| CRITICAL |   0   | —                                        |
| HIGH     |   0   | —                                        |
| MEDIUM   |   1   | safety-security (1)                      |
| LOW      |   1   | scope-creep (1)                          |

## Detailed findings

### MEDIUM

#### F-1 — safety-security: `tryMutateCookie()`'s catch-all contradicts its own docstring's scope claim
- Category: safety-security
- Path: `apps/web/src/lib/tokenStore.ts:119-126`
- Source: `tokenStore.ts`'s own module docstring (lines 38-49) + `FLAGS.md` AF-01 (mitigation-soundness is explicitly in scope for this review)
- Description: `tryMutateCookie()`'s comment states the swallow "is NOT a blanket error swallow for unrelated mutation bugs," but the implementation is exactly that: `catch { }` with no check on the error's type, name, or message, so it silently discards *any* exception `cookieStore.set()`/`.delete()` throws — not only the documented `ReadonlyRequestCookiesError` (Next.js seals the jar during a Server Component render). A future regression (e.g. a malformed cookie option, an oversized serialized session, or a genuine Next.js validation error introduced in a later version) would be indistinguishable from the accepted read-only-jar case and silently disappear from `page.tsx`'s render path — no log, no rethrow, no visible symptom beyond a session that mysteriously never persists a refresh. Note: `ReadonlyRequestCookiesError` is not exported from Next.js's public API (verified — it exists only in `next/dist/server/...` internals, not in `next/headers`'s public surface), so a precise `instanceof` narrowing isn't available without importing an internal, non-versioned path — this is a real constraint, not an oversight, and likely why the blanket form was chosen. But the docstring should say so plainly rather than claim a scoping the code doesn't perform.
- Suggested fix: Either (a) narrow the catch to the best available signal without an internal import — e.g. `error instanceof Error && error.constructor.name === "ReadonlyRequestCookiesError"` or a message-substring check — and rethrow anything else; or (b) if a public-API narrowing genuinely isn't feasible, correct the docstring to state plainly that the catch is unconditional by necessity (no exported error type to narrow on) rather than asserting a scoping guarantee the code doesn't provide. Either fix is small and does not change AC-5/AC-6/AC-8 behavior.

### LOW

#### F-2 — scope-creep: `docs/activity/activity.jsonl` rewrites a pre-existing SHP-01 telemetry line
- Category: scope-creep
- Path: `docs/activity/activity.jsonl` (the `/arh-implement feature:"SHP-01"` line, `duration_s` 9404→67844, `intervention_count` 13→14, cache/token counters also changed)
- Source: `tasks.json` `file_plan` (F-01..F-21) — this file is not in scope for any AUTH-05 task
- Description: this diff mutates an already-recorded telemetry line for a different, previously-shipped feature (SHP-01) in addition to appending AUTH-05's own new lines. This is very likely the harness's activity-logging hook re-flushing a session that was still open across feature boundaries, not a hand-edit by an implementation agent, and the file is append-only telemetry rather than application code or a governance artifact a reader binds to — but it has no citation in this story's `file_plan`/`tasks.json`, so it doesn't trace to a declared task per `surgical-changes`.
- Suggested fix: No action needed if confirmed as harness-generated telemetry flush (informational only). If it recurs across unrelated features' review cycles, worth a harness-side fix so a session's stats are attributed/flushed once, not revised retroactively under a later feature's diff.

## What went well

- ADR-0008's core invariant (no route hands a raw access token to client-side JS) is enforced at three independent levels: static code (no import), a runtime negative-assertion test (serializes every client-mock call arg and greps for `Authorization`/`accessToken`/the token literal), and a source-grep structural test — redundant verification of the single most important property this story ships.
- `D-08`'s module split (`programDetailApi.ts` vs `programDetailApi.client.ts`) is exactly what `reusability-baseline.md` asks for instead of a boolean-forked function — two small modules, same function names/result type, selected by import path rather than a runtime flag.
- `docs/requirements/auth.md`'s `session` contract and `docs/requirements/RTM.md` were updated in the same diff (multi-`produced_by`, new `frontend_ownership_note`) — no contract-drift.
- Every one of the 21 `file_plan` entries is accounted for in the actual diff; no file outside that plan was touched in `apps/web` or `services/api`.
- Test quality is unusually high throughout: faithful (non-canned) fakes for `callWithAuth` in the proxy-route unit tests actually exercise the `isUnauthorized` predicates passed in, rather than asserting on a hardcoded return.

## Recommendation

**PASS.** No CRITICAL or HIGH findings; one MEDIUM (documentation/implementation mismatch in a defensive catch, not a functional defect) and one LOW (likely-automated telemetry line outside declared scope). Neither blocks merge. Suggest addressing F-1 in a small follow-up (narrow the catch or fix its docstring) before this pattern is copied by a future story's Route Handler.
