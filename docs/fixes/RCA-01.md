# RCA-01 — `rebuild_program_rollups` aborts with IntegrityError when two programs share a session id

- Date: 2026-09-03
- Input: `"rebuild_program_rollups raises IntegrityError on user_sessions_session_identifier_key when a session_id appears under more than one program"` (found during a manual smoke run of all merged stories)
- Mode: investigate-only (`--debug`)
- For feature: BED-03 (defect surfaces there); root cause spans BED-01 and the unbuilt ingest write path

## Reproduction

Exact trigger, against a freshly migrated database:

1. Insert `usage_events` rows where the same `session_id` value occurs under two different `program_id`s — permitted by that table's own uniqueness key, `UNIQUE (program_id, session_id, cmd_ts)`.
2. `await rebuild_program_rollups(session, "payments")` → succeeds (`event_count=80`, 44 ms).
3. `await rebuild_program_rollups(session, "commerce")` → aborts.

```
psycopg.errors.UniqueViolation: duplicate key value violates unique constraint
  "user_sessions_session_identifier_key"
DETAIL:  Key (session_identifier)=(sess-0) already exists.
```

The whole rebuild transaction for `commerce` rolls back, so that program gets **no** rollup rows at
all — not a partial write, a total loss for that program. Re-seeding the same events with
program-prefixed (globally unique) session ids makes all three program rebuilds and the org rebuild
pass, with token and command aggregates matching the raw events exactly. That isolates the trigger to
the shared-session-id case precisely.

## Root cause

**Nothing enforces BED-01's documented "globally unique `session_identifier`" invariant at the point
data enters `usage_events`, which produces an unguarded `IntegrityError` that aborts an entire
program's rollup rebuild, because `rebuild_program_rollups` deletes only its *own* program's
`user_sessions` rows and then bulk-inserts `session_identifier=session_id` verbatim into a column
constrained `UNIQUE` across all programs.**

The two tables encode contradictory identity models:

| Table | Uniqueness | Implied model |
|---|---|---|
| `usage_events` | `UNIQUE (program_id, session_id, cmd_ts)` | a session id is scoped **per program** |
| `user_sessions` | `UNIQUE (session_identifier)` | a session id is **globally** unique |

`user_sessions` also *carries* a `program_id` column, and `rollup_rebuild.py:314` deletes by it —
both of which read as per-program row ownership, while the constraint says otherwise.

Critically, the global constraint is **intended, not accidental**: `docs/features/BED-01/DATA-DESIGN.md`
line 22 records `user_sessions` → "unique `session_identifier`" explicitly. So this is not a typo to
correct — it is a design invariant that no code enforces.

## Evidence

- `pg_constraint`: `user_sessions_session_identifier_key UNIQUE (session_identifier)` vs
  `uq_usage_events_program_session_cmd_ts UNIQUE (program_id, session_id, cmd_ts)`.
- `app/models/rollup.py:174` — `session_identifier: Mapped[str] = mapped_column(String, unique=True)`.
- `app/services/rollup_rebuild.py:314` — `delete(UserSessions).where(UserSessions.program_id == program_id)`,
  i.e. per-program delete against a global constraint.
- `app/services/rollup_rebuild.py:260-283` (`_build_user_sessions`) — groups by `e.session_id` and
  passes it straight through as `session_identifier`, with no cross-program dedupe or conflict handling.
- `docs/features/BED-01/DATA-DESIGN.md:22` — documents the global-uniqueness intent.
- `docs/features/BED-01/DATA-DESIGN.md:56` — states the `usage_events` compound key is "a foundation
  for BED-03's rollup-rebuild invariant", showing the two were reasoned about together without this
  contradiction being noticed.

## Reachability today

**Latent, not active.** The only route that could write `usage_events` is `/ingest/events`, which is
still a scaffold: its `_persist` is a `TODO(implementation)` that returns a response object and
writes nothing, and it requires no authentication. ING-01 shipped the token-minting CLI and the
`get_ingest_token` dependency but deliberately left wiring them to a route as ING-02's scope. So no
production path currently produces the triggering data — the events used to reproduce this were
hand-seeded with SQL.

Whether it becomes reachable depends entirely on a decision nobody has made yet: whether the ingest
source guarantees globally unique session identifiers. Claude Code session ids are UUIDs, which would
satisfy it incidentally — but nothing in the schema, the contract, or any ADR *requires* it.

## Classification

**architectural** — trips two of Step 1's bounce triggers:

1. **Changes a public contract / DB schema** and **touches the data model / requires a migration** —
   every candidate fix alters either a unique constraint (Alembic migration on `user_sessions`) or the
   ingest write contract.
2. **Contradicts a documented decision** — `BED-01/DATA-DESIGN.md:22` states the global-uniqueness
   design; flipping it to `(program_id, session_identifier)` silently reverses a merged, reviewed
   story's data-model decision, which `/arh-implement`'s G14 rule and `/arh-fix`'s own guard both
   forbid doing inside a fix lane.

The three viable resolutions are genuinely different products, which is itself why this needs the
Product Gate rather than a patch:

- **(a) Make the constraint compound** `UNIQUE (program_id, session_identifier)` — matches
  `usage_events`, matches the existing `program_id` column and per-program delete, and makes the same
  human session legitimately appear under two programs. Amends BED-01's DATA-DESIGN.
- **(b) Keep global uniqueness and enforce it at ingest** — ING-02/03 reject or namespace a session id
  already bound to a different program. Keeps BED-01 as documented; adds a real ingest requirement.
- **(c) Keep global uniqueness and make BED-03 degrade** — detect the collision and skip or merge the
  row with a diagnostic, instead of losing the whole program's rebuild. Weakest: it preserves
  contradictory models and hides bad data.

## Recommended next

`/arh-intake "Reconcile session identity between usage_events and user_sessions, and enforce it at the ingest write path — rollup rebuild currently loses an entire program's rollups with an unguarded IntegrityError when one session id spans two programs"`

Route to full intake (research → PRD → plan → Product Gate), not `/arh-fix`. Sequence it **before
ING-02/ING-03 build the real ingest write path**, since option (b) would land as a requirement on
those stories and option (a) needs its migration before real data accumulates.

Interim: no code change. The risk is inert while `/ingest/events` persists nothing.
