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
