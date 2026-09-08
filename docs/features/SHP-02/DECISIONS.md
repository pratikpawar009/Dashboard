# SHP-02 — Decisions

Decision log for the personal usage panel backend. D-01..D-03 close research Conditions C-1..C-3
and C-5; D-04 closes C-4 and is promoted to `docs/adr/0009-personal-usage-api-response-shape.md`.

### D-01: `user_sessions` backs cards + daily chart, `usage_events` backs commands only — 3 bounded SELECTs, plain (non-`CONCURRENTLY`) additive index migration · blast:feature · rev:mechanical · adr:—

**Context**: Research Condition C-2 requires the table-to-panel mapping fixed before coding, and
Condition C-1 requires a new index to keep this cross-program, per-user query pattern under
NFR-002's ≤2s budget (neither `user_sessions` nor `usage_events` carries a usable index today —
`user_sessions` has none beyond `session_identifier` uniqueness; `usage_events`'s four indexes are
all `program_id`-prefixed). Separately, `usage_events` has no retention policy and grows
unboundedly, org-wide (`docs/requirements/data.md:55`) — a `CREATE INDEX` (non-`CONCURRENTLY`)
against it takes a brief `ACCESS EXCLUSIVE`-adjacent write lock during the index build, which
matters more the larger that table gets in production.

**Decision**: `user_sessions` (already session-granular, carries `tokens`/`duration_seconds`)
backs the 4 cards (one to-date aggregate `SELECT`) and the daily token chart (one range-scoped
grouped `SELECT`); `usage_events` backs the commands breakdown only (one range-scoped grouped
`SELECT`) — exactly 3 bounded `SELECT`s per request, verified by `test_personal_usage_perf.py`'s
query-count spy (T-09), regardless of either table's row count. The new Alembic migration
(`002_personal_usage_indexes.py`, T-01) adds `Index("ix_user_sessions_user_id_started_at",
"user_sessions", "user_id", "started_at")` and `Index("ix_usage_events_user_ts", "usage_events",
"user", "ts")` using plain `op.create_index(...)` — **not** `postgresql_concurrently=True` — matching
this repo's one existing migration's convention (a single in-transaction `upgrade()`) and avoiding
introducing `autocommit_block()` machinery with no precedent anywhere in this codebase, no CI
pipeline to validate it (`CI: none`), and a real interaction risk with the `AlembicRunner`
test fixture's thread-dispatched `alembic.command.upgrade`. The production write-lock tradeoff is
accepted and disclosed here, not silently introduced: this project has no deploy runbook today (no
CI, `docs/config/project-commands.yaml` `Migrate:` is a manual step) to carry a
"run this migration during a maintenance window" instruction, so a `CONCURRENTLY` migration would
be unused sophistication without an operational process to require it. This does not need promotion
to a full ADR: the migration is index-only (no column/encoding/retention change), trivially
reversible via `alembic downgrade` dropping the two indexes, and this repo's existing index-bearing
tables (`program_releases`, `program_commands`, `program_members`) were likewise never promoted.

### D-02: Default-range wrapper is story-local; `app/dependencies/range.py` is never edited · blast:feature · rev:mechanical · adr:—

**Context**: Research Condition C-3 / Risk #2: `validate_range`'s only signature takes `range:
str = Query(...)` (required) — AC5's "default to 30d when omitted" is unimplemented anywhere in
the codebase, and `docs/requirements/api.md#api-conventions` states wiring the default is
"explicitly each downstream story's own scope." Editing the shared dependency's signature would
touch 15 other declared consumers of `api-conventions` for a single story's need.

**Decision**: `app/api/personal_usage.py` defines a private
`_range_with_default(request: Request, range: str = Query("30d")) -> str: return
validate_range(request, range)` and wires it via `Depends(_range_with_default)` in place of
`Depends(validate_range)`. It supplies only the `Query` default; the `{7d,30d,90d}` membership
check, the `HTTP 400` rejection, and the `invalid_range` warning log stay entirely inside the
shared `validate_range()`, unedited (`app/dependencies/range.py` is not in this story's file plan).
FastAPI resolves `Depends()` parameters before the handler body runs, so an invalid `range` on a
cross-user request 400s before `individual_usage_visibility` is ever evaluated — this is FastAPI's
own dependency-resolution order, not a discretionary choice, and is consistent with
`api-conventions`' "identical 400 status + error body across every consumer" invariant.

### D-03: `bar_style_for_share()` added to the shared `app/utils/format.py`, not story-local · blast:feature · rev:mechanical · adr:—

**Context**: `commands[].barStyle` needs a server-computed, ready-to-bind CSS width string — the
same "producer computes CSS" shape `dot_style_for_program()` already established in
`app/utils/format.py` for `programs-api`'s `dotStyle`. Duplicating that shape as a story-local
helper inside `app/services/personal_usage.py` would fork a pattern this codebase already
centralizes (`.claude/rules/reusability-baseline.md`: DRY across modules of the same concern).

**Decision**: Add `bar_style_for_share(count: int, max_count: int) -> str` to
`app/utils/format.py`, returning `f"width: {round(count / max_count * 100)}%;"` (`"width: 0%;"`
when `max_count == 0`, i.e. no commands in range). Purely additive — no existing `format.py`
signature changes, so none of `api-conventions`' 15 other consumers are affected. Mechanical to
move or revert.

### D-04: `personal-usage-api` response envelope — 4-field-locked cards (5 keys, no `delta`), range-scoped `daily_tokens`/`commands`, max-of-range bar formula · blast:system · rev:medium · adr:ADR-0009

**Context**: Research Condition C-4 / Risks #3, #4, #5: the decoded ARC/DEV/PMD mockups (md5-identical
bindings) bind 5 card fields (`glyph, value, label, iconBg, iconColor`) where AC1/`api.md`'s sketch
named only 4; the mockup's `k.delta` mock-data field is bound in zero templates; AC3's "share of
the total run count" prose disagrees with the mockup's actual `cmax = Math.max(...cmdCounts)`
formula. Four not-yet-built sibling stories (ARC-01, DEV-01, PMD-01, PGD-05) already declare a hard
dependency on this shape — a later correction is a 4-way breaking change (Risk #5).

**Decision**: Locked and promoted to `docs/adr/0009-personal-usage-api-response-shape.md` — see
that ADR for the full envelope shape, the cards-are-to-date-vs-daily_tokens/commands-are-ranged
split, and the `count / max(counts) * 100` bar formula. `blast:system` (a sealed cross-feature
contract) and `rev:medium` (no persisted data depends on it, but 4 consumers would need updating)
both independently trigger promotion per the `decide` skill's rule.

### D-05: ORM `Index()` declarations mirror the new migration in `app/models/rollup.py`/`ingestion.py` · blast:feature · rev:mechanical · adr:—

**Context**: This repo's existing index-bearing rollup tables (`ProgramReleases`,
`ProgramCommands`, `ProgramMembers`) all declare their migration's index via `__table_args__` —
`UserSessions` (no `__table_args__` today) and `UsageEvent` (four existing `program_id`-prefixed
indexes) would otherwise drift from the schema the new migration (D-01) actually creates once this
story lands, since `target_metadata = None` means no autogenerate diff would ever catch it
(`alembic-patterns` skill § Verified facts).

**Decision**: Add `Index("ix_user_sessions_user_id_started_at", "user_id", "started_at")` to
`UserSessions.__table_args__` and `Index("ix_usage_events_user_ts", "user", "ts")` to
`UsageEvent.__table_args__`'s existing tuple (T-02) — matching D-01's migration exactly, keeping
the ORM model and the live schema in agreement for the next developer who reads the model instead
of the migration history.
