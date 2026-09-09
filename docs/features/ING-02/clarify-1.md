# ING-02 — Clarification round 1

**Status**: resolved · **Asked**: 2026-09-09 · **Answered**: 2026-09-09 by Pratik Pawar

Source markers: `docs/research/ING-02.md` § Clarifications (3 markers, research-phase).

> Round-trip compressed: the PO answered in-session, so this artefact was written with
> answers already filled rather than issued blank and re-imported via `--apply`. The
> audit trail is the same; only the latency differs.

---

## integration

### Q-01 — `rows[]` wire shape
**Marker** (`docs/research/ING-02.md`, C-1): are `rows[]` field names the raw `activity.jsonl`
ones with the API aliasing them to `usage_events` columns, or does the producer rename before
POSTing? Are unmapped fields (`source`, `copilot_credits`) ignored or rejected?

**Blocking**: the `ingest-files-api` contract, which ING-02/04/06/09 all bind to.

**Answer**: **Persist everything — "save all data in tables, we may need this in future for
different operations."**

Resolved shape:
- Producer POSTs the raw `activity.jsonl` field names; the API aliases the five that differ
  (`duration_s`→`duration_seconds`, `input_token`→`input_tokens`, `output_token`→`output_tokens`,
  `cache_read`→`cache_read_tokens`, `cache_write`→`cache_write_tokens`). The producer stays
  decoupled from DB column names.
- `source` and `copilot_credits` are **stored, not dropped**. `usage_events` has no column for
  either, so this requires an **additive migration** adding them — the ING-10 `003_program_roster`
  pattern (additive only, no change to existing columns or behaviour).
- Consequence for planning: an unknown field must not be silently discarded. Either the schema
  gains a column for it or the batch surfaces it — planning picks the mechanism.

---

## scope

### Q-02 — which `kind` does AC-5 mean?
**Marker** (`docs/research/ING-02.md`, C-2): the request envelope `kind` (`activity`/`artifacts`)
or the per-row `usage_events.kind` (nullable, no vocabulary, zero readers in `app/`)?

**Blocking**: AC-5's per-row rejection tier, and whether AC-4's abort tier grows a case.

**Answer**: **Envelope only; the row's `kind` is stored verbatim with no validation.**

- The envelope `kind` is a request-level fact — validating it belongs in **AC-4's whole-request
  abort tier**, not AC-5's per-row bucket.
- Row-level `kind` is written as received. Evidence: all 77 rows in the current
  `docs/activity/activity.jsonl` carry `kind: "command"`, and nothing in `app/` reads the column.
- **AC-5 must be reworded** to drop its "unrecognized `kind`" clause; its remaining cases
  (malformed ISO date, missing required field) stand unchanged.

---

## integration

### Q-03 — synchronous rollup, and who may edit BED-03
**Marker** (`docs/research/ING-02.md`, C-3): does AC-1's synchronous rebuild hold given the
measurements, and may ING-02 modify BED-03's shipped `app/services/rollup_rebuild.py` against the
standing "no validated story reopens" rule?

**Blocking**: AC-1, the p95 ≤ 3s NFR, and both CRITICAL risks.

**Answer**: **A new story owns the rollup fix; ING-02 depends on it.**

- ING-02 does **not** edit `rollup_rebuild.py`. The standing rule holds — the same rule that
  forced ING-10 to create `program_roster` rather than touch `program_members`.
- The new story owns, at minimum: the org-singleton concurrency failure
  (`org_summary_rollup_org_id_key`, 2 of 4 concurrent pushes on distinct programs), the unbounded
  whole-table `select(UsageEvent)` at `rollup_rebuild.py:470`, and the rebuild cost that scales
  with accumulated table size rather than batch size (588ms → 4,805ms program, 417ms → 3,864ms org
  across 20k → 160k rows).
- It gets its own gate rather than riding in the endpoint PR — bundling a rewrite of shipped
  internals every ingest path depends on into a new-endpoint PR is the pattern
  `.claude/rules/surgical-changes.md` forbids.
- **ING-02 is blocked on that story**, and its p95 NFR cannot be re-baselined until the fix lands.

---

## Consequences for the next phases

1. The new BED rollup story must be created (`/arh-intake`) and taken through to implementation
   before ING-02 can meet AC-1.
2. `usage_events` needs an additive migration for `source` + `copilot_credits` (Q-01). Additive
   only — it does not reopen BED-01's existing columns.
3. AC-5's wording changes (Q-02); AC-4 gains the envelope-`kind` abort case.
4. `docs/requirements/api.md#ingest-files-api` must pin the resolved wire shape once, since four
   stories bind to it.
