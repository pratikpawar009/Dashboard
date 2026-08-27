# BED-02 — Decisions

Non-trivial technical choices made while planning BED-02's shared API-conventions layer. Header slugs (`blast:`/`rev:`/`adr:`) are machine-greppable per the `decide` skill.

### D-01: Pagination helpers clamp out-of-range values instead of rejecting them · blast:service · rev:mechanical · adr:—

**Context**: AC 3/AC 4 require `limit`/`page_size` to be *clamped* to a max (50 / 100) when omitted or over-max — never rejected. FastAPI's declarative `Query(..., le=N)` constraint raises HTTP 422 on an over-max value, which is the opposite of the required behaviour, and TC-05/TC-07 assert a 200-equivalent clamp, not a 4xx.

**Decision**: `app/dependencies/pagination.py`'s `get_offset_limit`/`get_page_params` declare `Query()` bounds with `ge=` only (no `le=`), then manually clamp via `min(value, MAX)` inside the function body before returning the resolved tuple. Defaults are set to the max itself (`limit` default 50, `page_size` default 100) so an omitted param also resolves to the documented max, matching TC-05/TC-07's omitted-value expectation.

### D-02: Derived-value functions accept pre-fetched ORM rows, not a DB session · blast:service · rev:mechanical · adr:—

**Context**: AC 5 requires derived values (adoption %, delta, average, "X/Y passing") computed server-side in `services/api/app/services/*.py`, reading from BED-01's rollup/governance models. No persistence layer exists yet (`fastapi-patterns`: routers are still `TODO(implementation)` stubs) — the function boundary needs deciding: does the services layer own the query, or just the computation?

**Decision**: Every `services/*.py` function takes an already-fetched ORM model instance (or a list of them) as input and returns a `dict` merging the raw counts with the computed field(s) — never just the raw counts, satisfying TC-09's "the raw component counts alone... are never the sole payload" requirement. Query construction stays with the (future) router/persistence layer, keeping `services/*.py` pure and DB-session-free for unit testing.

### D-03: Compute modules split rollup vs. governance, mirroring BED-01's model-file split · blast:feature · rev:mechanical · adr:—

**Context**: BED-01 (D-02, `docs/features/BED-01/DECISIONS.md`) grouped ORM models into `rollup.py`/`governance.py`/`ingestion.py`. BED-02's services layer computes over both the rollup group (adoption %, delta, average) and the governance group (guardrail "X/Y passing").

**Decision**: `app/services/rollup_compute.py` (`compute_adoption_percent`, `compute_period_delta`, `compute_average`) and `app/services/guardrail_compute.py` (`compute_guardrail_summary`) — one compute module per model group, so a function's file location predicts which model group it reads.

### D-04: `JSONFormatter` excludes a hardcoded `LogRecord`-reserved-attribute set, not a dynamically computed one · blast:service · rev:mechanical · adr:—

**Context**: FR-3 requires `JSONFormatter.format` to merge `extra` fields into the JSON payload while excluding Python's standard `LogRecord` attributes (TC-16). Computing the reserved set dynamically (e.g. from a throwaway `LogRecord` instance's `vars()`) risks drifting across Python versions (3.12 added `taskName`) and obscures exactly what is excluded from a payload every log line in the service goes through.

**Decision**: `app/core/logging.py` defines an explicit module-level `_RESERVED_LOGRECORD_ATTRS` frozenset (`name, msg, args, levelname, levelno, pathname, filename, module, exc_info, exc_text, stack_info, lineno, funcName, created, msecs, relativeCreated, thread, threadName, processName, process, message, asctime, taskName`) and merges every `record.__dict__` key not in that set into the payload.

### D-05: `program_guardrails.status == "Enforced"` is what counts as "passing" in the X/Y summary · blast:feature · rev:mechanical · adr:—

**Context**: `program_guardrails.status` is a 3-value enum — `Enforced|Warning|NotImplemented` (`docs/requirements/data.md` `#db-schema`). Neither AC 5's "X/Y passing" wording nor TC-10's test data states which enum value counts as "passing" for the numerator.

**Decision**: `compute_guardrail_summary` treats `status == "Enforced"` as the passing state (guardrail actively enforced and verified); `Warning`/`NotImplemented` count toward the total denominator only. The mapping is stated in the function's docstring formula so downstream PGD/EMD implementers don't have to reverse-engineer it from the enum.

### D-06: `range_to_start` returns timezone-aware UTC and rejects a naive `now` · blast:service · rev:mechanical · adr:—

**Context**: Not anticipated at plan time. `range_to_start` was first written with a bare `datetime.now()`, producing a naive datetime. Every timestamp column BED-01 migrated is `DateTime(timezone=True)` (`app/models/rollup.py:34-36,47,61,85,96,99,110-111`), and this function's only purpose is producing the lower bound for a query against exactly those columns (AC 1). A naive bound either raises `TypeError: can't compare offset-naive and offset-aware datetimes` or silently compares a local wall clock against UTC-stored data.

**Decision**: the default reference is `datetime.now(UTC)`, matching the convention `app/core/logging.py` already uses. A caller-supplied `now` that is naive raises `ValueError` rather than being coerced — coercion would assume the caller meant UTC, and if that assumption is wrong the error surfaces later as silently wrong data instead of immediately as a bad argument. Stated in the docstring so consumers know the return is aware UTC.

### D-07: `adoption_percent` is `None`, not `0.0`, when `programs_total == 0` · blast:feature · rev:mechanical · adr:—

**Context**: Not anticipated at plan time. `compute_adoption_percent` transcribed its formula directly and divided without a zero guard, while both sibling functions in the same module already guarded theirs. `OrgSummaryRollup.programs_total` carries no non-zero constraint, so a rollup row for an org onboarded before any program is registered is a reachable `ZeroDivisionError`.

**Decision**: return `None`, following `compute_period_delta`'s absent-baseline precedent rather than `compute_average`'s `0.0`. `0.0` would assert that every one of zero programs failed to adopt AI — a category error conflating "nothing to measure" with "measured and found zero". The CIO Portfolio mockup renders this as a headline figure, where a false 0% misleads worse than an explicit blank.

**Consequence**: `docs/requirements/api.md#api-conventions` states the formula without a `None` case, so its `adoption_percent` entry is now incomplete. T-18 (contract reconciliation) must record the nullable case — 13 downstream stories read that contract and will need to render a null.

### D-08: `compute_guardrail_summary` returns `0/0 passing` for an empty sequence, with no `None` guard · blast:feature · rev:mechanical · adr:—

**Context**: Not anticipated at plan time; raised by the T-06 worker after D-07 established a `None`-on-empty-denominator precedent in the sibling module. A program with no guardrails configured is reachable, so the empty-sequence case needed an explicit answer.

**Decision**: return `passing_count=0, total_count=0, summary="0/0 passing"` — no `None`. This case is genuinely unlike D-07's despite the surface similarity: `compute_guardrail_summary` performs **no division**. `passing_count` and `total_count` are literal counts formatted into a string, so there is no division by zero to guard. "0 of 0 guardrails passing" is an accurate and renderable statement, whereas a null percentage is not a number a dashboard can display.

### D-09: `format_number`'s boundary behaviour is the contract; bucket must agree with the rendered value · blast:feature · rev:mechanical · adr:—

**Context**: `docs/requirements/api.md` gives only three examples (`2500 -> "2.5K"`, `1_500_000 -> "1.5M"`, `125 -> "2h 5m"`). Everything else — sub-1000 values, exact boundaries, rounding vs truncation, trailing `.0`, negatives, zero — was undefined, and 13 consumer stories render these strings. An undocumented choice here becomes 13 dashboards' worth of inconsistency.

**Decision**: the module docstring is the contract. Bucket is chosen from `abs(value)`; boundaries belong to the upper bucket (`1_000 -> "1.0K"`); one decimal is always kept including a trailing `.0` (`2000 -> "2.0K"`) for consistent column width; `:.1f` rounds rather than truncates; sub-1000 renders as a bare rounded integer; negatives keep their sign and bucket on magnitude. `format_duration` drops the minutes term on exact hours (`120 -> "2h"`), renders `0 -> "0m"`, and **rejects** negative input with `ValueError` rather than coercing, because `divmod` floors toward negative infinity and would otherwise render a negative duration as a positive one.

**Correction applied during implementation**: the first version selected the bucket from the unrounded magnitude while rendering the quotient rounded to one decimal, so the two could disagree — `format_number(999_999)` returned `"1000.0K"` and `format_number(999_999_500)` returned `"1000.0M"`, both with plain integer input, which is precisely the un-abbreviated output the suffix exists to prevent. Bucket selection now follows the value as rendered, promoting when the rounded quotient reaches 1000.
