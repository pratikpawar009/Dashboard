# FLAGS — SHP-03

## F-01 · spec-conflict · T-01 · risky-pattern

`DECISIONS.md` D-02's prose ("delegates to `format_number()` for the M/K magnitude/rounding
logic") contradicts `DESIGN.md` § Value formats, whose generator expression
(`Math.round(tk*1000)+'K'`) and point 3 both mandate a **whole-number K, no decimal**.
`format_number()`'s K branch always renders `.1f` (`"840.0K"`), never `"840K"`.

Resolved in DESIGN.md's favour per CLAUDE.md § Design system (the mockup settles response
shape). `format_session_tokens()` delegates to `format_number()` only at/above 1M; below 1M it
computes `f"{round(tokens/1000)}K"`. `format_number()` and `format_duration()` remain untouched
(D-01/D-02 seal intact).

**Action:** correct D-02's wording so a future reader does not "fix" this back.

## F-02 · boundary-behaviour · T-01 · review-me

Two consequences of following the generator literally, both verified against the shipped
function:

1. `format_session_tokens(999_999) -> "1000K"`. The K tier has no promote-to-M rule, so a value
   one token below 1M renders as `"1000K"` where the sibling `format_number()` would promote it
   to `"1.0M"`. The design source never exercises this boundary (its generator only produces
   values from `0.35M` to `1.5M`), so this is an un-designed edge, not a drawn one.
2. `format_session_tokens(2_500) -> "2K"`, not `"3K"`. Python's `round()` is banker's rounding
   (half-to-even); JS `Math.round` is half-up. Exact `.5` multiples of 1000 therefore differ
   from the generator by one unit.

Neither is covered by a mockup state. Raised for review rather than fixed, since "match the
generator" and "match `format_number()`'s promotion" point in different directions and the
choice is a product call.

## F-03 · data-reality · T-04 · review-me

`user_sessions.name` — which this story renders as the table's `title` column, the widest
column in the mockup — is **not a session title in production**. The rollup producer
(`services/api/app/services/rollup_rebuild.py:377-379`) sets `name=user`, documenting that
`name` "has no `usage_events` analog and falls back to the `user` identifier" (its own D-03).

Consequence: every row's `title` will render the same value — the user's email/identifier —
because the list is already scoped to a single user. The mockup shows descriptive titles
("Refactor auth middleware", etc.) supplied by its sample-data generator, which has no
production counterpart.

This story implements the contract correctly (`title` = `user_sessions.name` verbatim, per
FR-1); the gap is upstream in what populates `name`. Not fixable here without inventing a title
source that the ingest path does not carry.

**Action:** raise with the PO. Either the ingest path needs to carry a session title, or the
panel's first column needs a different treatment. Do not "fix" it by synthesising a title in
this story's service layer.

## F-04 · plan-defect · T-07/T-16 · review-me

`PLAN.md` § 7 Test Strategy cites three test-case ids that **do not exist**. `docs/test-cases/
SHP-03.json` declares exactly `SHP-03-TC-01` .. `SHP-03-TC-11`; PLAN.md additionally cites
`TC-12`, `TC-13` and `TC-14`.

Mapping of what the invented ids were evidently meant to be:

| PLAN.md cites | Against | Actually |
|---|---|---|
| `TC-14` | `tests/perf/test_personal_sessions_perf.py` | `TC-11` — the only `type: performance` case, whose `test_data` (250 rows, `page=2&page_size=20`, `query_count_budget: 2`, `latency_budget_ms: 2000`) matches exactly |
| `TC-12`, `TC-13` | `SessionsTable.test.tsx` | no counterpart — the component's a11y/state coverage was never given test-case ids |

Caught by the T-07 worker, which wrote its test against TC-11's real content and reported the
discrepancy rather than silently "correcting" PLAN.md. The T-16 dispatch had already quoted
TC-12/TC-13 before this was found.

Consequence: the plan's own traceability table does not reconcile with the approved test-case
manifest, and `/arh-validate-feature` reads that manifest. No production behaviour is affected.

**Action:** correct PLAN.md § 7 to cite `TC-11` for the perf row, and either add real test cases
for the component coverage or mark that row as having no numbered TC (the proxy-route row
already uses the "— (proxy plumbing, not a numbered TC)" convention for exactly this situation).

## AF-05 · evidence-na · task: n/a · docs/config/project-commands.yaml

`design_check` dimension marked N/A during the end-of-session evidence pass — `project-commands.yaml`'s
`design_check:` key is deliberately empty (no a11y/console-error-scan/perf tool wired yet; the file's own
comment documents this as intentional pending tool selection, e.g. axe-playwright or pa11y-ci). No UI
regression signal is missing beyond what typecheck/lint/unit tests + the manual runtime render check
(HTML fetch confirming the app mounted real content, not a bare root) already covered this session.

## F-05 · test-coverage-gap · validation gate · follow-up

`SHP-03-TC-01` (the `meta` composite string) and `SHP-03-TC-02` (the exact `started_at DESC,
id ASC` tiebreak) have **no dedicated automated assertion of their literal expected output**
anywhere in the repo. `tests/unit/test_personal_sessions_route.py`'s own docstring says this
coverage is "owned elsewhere", but no other file actually asserts it — the T-06 worker scoped
TC-01/TC-02 out on that basis, and nothing picked them up.

Both were verified correct by direct source inspection during the validation gate
(`app/services/personal_usage.py::_build_session_entry` and `fetch_sessions_paginated`), and the
response envelope is live-confirmed, so the verdict stands at PASS. But the two contracts most
likely to be broken by a careless future edit — the pre-joined `meta` format and the ordering
tiebreak that makes pagination deterministic (research risk R-02) — are currently unguarded by a
test that would fail.

**Action:** add literal-output assertions before ARC-01/DEV-01/PMD-01 begin consuming `meta`
verbatim. Seeding non-empty `user_sessions` rows is the only setup needed; the T-06 file already
has fixtures that do it.
