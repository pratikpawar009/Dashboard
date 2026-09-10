/**
 * `overview-summary-api` wire shapes (OVW-01, DECISIONS.md D-01/D-02).
 */

/**
 * One of the 5 order-locked `ORG SUMMARY` cards (DECISIONS.md D-01/D-02).
 *
 * Unlike `program-detail-api`'s genuinely 3-field `ProgramSummaryCardData`
 * (that mockup binds only `s.glyph`/`s.label`/`s.value`), this card shape
 * carries a 4th field, `sub` -- the CIO Portfolio mockup's `ORG SUMMARY`
 * template also binds `k.sub`. `sub` is `null` on every card except card 1
 * (`programs_using_ai`), which carries `"{pct}% adoption"` (or `null` when
 * `programs_total === 0`, since `adoption_percent` is `null` then too).
 */
export interface OrgSummaryCardData {
  glyph: string;
  value: string;
  label: string;
  sub: string | null;
}

/**
 * Raw adoption counts, shared by card 1 and the `Adoption Level` indicator
 * region (DECISIONS.md D-01/D-02, D-05/D-06). `count`/`total` are raw
 * numbers -- needed verbatim for the indicator's literal `<count>/<total>`
 * headline and per-segment legend counts, not pre-formatted strings.
 * `adoption_percent` is `number | null` and is `null`, never `0`, when
 * `total === 0` -- covers both the missing-rollup-row (AC-2) and
 * genuinely-zero-programs cases alike; the client must not divide/round on
 * a `null` value (`OVW-01-FR-4` zero state).
 */
export interface ProgramsUsingAiData {
  count: number;
  total: number;
  adoption_percent: number | null;
}

/**
 * Response envelope for `GET /api/overview/summary`. `cards` is exactly 5
 * entries in mockup order -- order is the contract, never re-sorted by a
 * consumer. `programs_using_ai` is a separate top-level structure, not
 * folded into `cards`, since it also drives the `Adoption Level` indicator
 * section, not just card 1.
 */
export interface OverviewSummaryData {
  cards: OrgSummaryCardData[];
  programs_using_ai: ProgramsUsingAiData;
}

/**
 * `fetchOverviewSummary()`'s result. `"forbidden"` is new relative to
 * `ProgramDetailResult` (`@/types/programDetail`) -- this endpoint is
 * cio-only (`org_access`, AC-3), so a non-cio persona's 403 needs its own
 * outcome, distinct from the existing `"unauthorized"` (401) vocabulary.
 */
export type OverviewSummaryResult =
  | { status: "ok"; data: OverviewSummaryData }
  | { status: "forbidden" }
  | { status: "unauthorized" }
  | { status: "error" };
