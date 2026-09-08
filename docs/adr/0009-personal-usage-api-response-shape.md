# ADR-0009: `personal-usage-api` returns 5-field cards + a raw daily token series + a commands panel, server-owned presentation fields

- Status: Accepted
- Date: 2026-09-07
- Deciders: pratik.pawar@apexon.com (via impl-planning-agent, `/arh-plan-implementation SHP-02`)

## Scope note (reused ADR number)

`docs/requirements/RTM.md` § Decisions (2026-09-07) records that a prior tracker comment
(issue #213) cited a nonexistent **"ADR-0009 (Accepted, 2026-09-04)"** for SHP-02's *frontend chart
rendering* (inline SVG bars vs. a charting library) — that ADR was never authored in this repo,
and RTM explicitly declines to backdate one. This ADR legitimately reuses the number `0009` (the
first free id — `docs/adr/` ends at `0008` as of this writing) for a different, in-scope decision:
the **wire shape** `personal-usage-api` returns. It does not settle, and does not reference,
frontend chart rendering — that remains open per RTM's 2026-09-07 entry and must be decided before
ARC-01/DEV-01/PMD-01 (the `{{ tokChart }}` consumers) are planned.

## Context

`docs/requirements/api.md#personal-usage-api` is a sealed contract:
`consumed_by: [ARC-01, DEV-01, PMD-01, PGD-05]`, all four `validated` but none implemented yet
(research Risk #5) — this story is the one chance to lock the shape before four sibling stories
build fixtures against it, the same situation ADR-0005 (`programs-api`) and ADR-0007
(`program-detail-api`) already resolved for their own endpoints.

The story AC prose and `api.md`'s pre-fill sketch under-specify three things the decoded
Architect/Developer/Product-Manager mockups (md5-identical section lists and bindings) settle
concretely, per `CLAUDE.md` § Design system (the mockup, not PRD prose, is authoritative for
response shape):

1. **Cards carry 5 bound fields, not 3.** `myKpis` binds `k.iconBg`, `k.iconColor`, `k.glyph`,
   `k.value`, `k.label` (template lines 419-423) — AC1/`api.md`'s sketch name only the 4 card
   identities and `value`. The mock-data generator's `k.delta` (line 870) is bound in **zero**
   templates across all three mockups — a dead field that must not reach the wire.
2. **The daily token chart is a raw numeric series**, following `overview-token-series-api`'s
   (OVW-02) already-shipped precedent of "N `{period, value}` points" for the same binding class
   (`{{ tokChart }}` renders client-side from data) — not server-rendered markup.
3. **`commands[].barStyle`'s width formula disagrees with AC3's own prose.** AC3 reads "a bar
   proportional to its share of the total run count" (i.e. `count / total * 100`), but the decoded
   mockup computes `cmax = Math.max(...cmdCounts)` (line 999) — proportional to the single largest
   command, `count / max(counts) * 100`. Recorded here (and in the PRD's `SHP-02-FR-3`) as a
   resolved discrepancy, not a future defect.

## Decision

`GET /api/personal-usage/{user_id}?range=7d|30d|90d` (default `30d`) returns:

```yaml
cards: [ { glyph, value, label, iconBg, iconColor }, ... ]   # exactly 4, mockup order is part of the contract
daily_tokens: { points: [ { date, value }, ... ], period_total, avg_per_day }
commands: { total_runs, items: [ { command, count, barStyle }, ... ] }
```

- **`cards`** — exactly 4 entries, **order-locked**: Sessions, Total time, Total tokens,
  Avg tokens/session. `glyph`/`iconBg`/`iconColor`/`label` are fixed presentation constants owned
  by the producer (mirrors `program-detail-api`'s `_SUMMARY_CARD_GLYPHS_LABELS` precedent, extended
  to a 4-tuple), zipped against the one varying `value` per card. `value` is pre-formatted:
  `format_number()` for Sessions/Total tokens/Avg tokens per session, `format_duration()` for Total
  time (both `api-conventions`, BED-02). **No `delta` field ships, ever** — it exists only in the
  mockup's mock-data generator, bound nowhere.
- **`daily_tokens`** — `points` is one `{date, value}` entry per day in the selected range (7/30/90
  points), zero-padded for a day with no sessions, oldest-to-newest, `value` pre-formatted via
  `format_number()`; `period_total`/`avg_per_day` are the PRD's own literal field names (FR-2),
  both pre-formatted via `format_number()`.
- **`commands`** — `total_runs` (pre-formatted `format_number()` string, sum of in-range command
  counts); `items` is one `{command, count, barStyle}` entry per distinct command seen in the
  range, `count` a **raw int** (the bar-formula input, not pre-formatted — matching this field's
  role as the denominator/numerator source, not a display value on its own), `barStyle` a
  ready-to-bind CSS width declaration (mirrors `dot_style_for_program()`'s "producer computes CSS"
  precedent, `app/utils/format.py`): `f"width: {round(count / max(all in-range counts) * 100)}%;"`
  — **max-of-range, not share-of-total** (point 3 above).
- Cards are a **to-date** aggregate (all sessions ever, unbounded by `range`); `daily_tokens` and
  `commands` are **range-scoped**. Both are correct simultaneously — they answer different
  questions ("how much have I done, ever" vs. "what does my recent activity look like") — and
  neither is a bug relative to the other.
- No `program_id` anywhere in the request or response — "my usage" is a cross-program aggregate by
  contract (`docs/requirements/api.md#personal-usage-api`, unchanged by this ADR); PGD-05 reuses
  this endpoint verbatim and inherits the same org-wide scope for its per-member popup
  (`docs/requirements/RTM.md` § Decisions, 2026-08-26).

## Consequences

- Positive: every field this endpoint returns traces to a mockup binding or a PRD-literal field
  name (`period_total`, `avg_per_day`, `barStyle`) — no invented field survives to the wire. One
  producer-owned source of truth for card glyph/label/order/iconBg/iconColor: ARC-01, DEV-01,
  PMD-01, and PGD-05 each render via a plain map over `cards`, zero per-consumer duplication of
  presentation constants (same benefit ADR-0007 documented for `program-detail-api`'s `summary`).
- Negative: array position replaces field name as the cards' addressing mechanism (same
  ADR-0007 trade-off); `commands[].count` deliberately breaks the "everything pre-formatted"
  convention (it must stay a raw int for the bar-formula denominator to be computable without a
  second, un-formatted field) — a consumer wanting a display string must call `format_number()`
  itself for `count`, an explicitly narrow, documented exception, not a general license to ship
  unformatted numerics elsewhere in this response.
- Reversible? Medium — no persisted data depends on this shape (BED-01's `user_sessions`/
  `usage_events` are unchanged); reversing it means updating this Pydantic response model plus
  every consumer built against it by then. Low cost today (zero consumers implemented yet, all
  four still `story-validated`); rising cost as ARC-01/DEV-01/PMD-01/PGD-05 land.

## Flagged gaps

- Frontend chart-rendering approach for `{{ tokChart }}` (inline SVG bars vs. a charting library)
  is **not** settled by this ADR — see the Scope note above. It remains open per
  `docs/requirements/RTM.md` § Decisions (2026-09-07) and must be resolved, as its own ADR, before
  ARC-01/DEV-01/PMD-01 plan their consumption of `daily_tokens.points`.
