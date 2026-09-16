/**
 * `program-token-trend-api` wire shapes (PGD-02, DECISIONS.md D-02/D-03/D-04).
 */

/**
 * Mirrors backend `ProgramTokenPoint` (`services/api/app/schemas/program_detail.py`).
 * Deliberately NOT `personal_usage`'s `DailyTokenPoint` -- that sibling's `value` is a
 * pre-formatted string; `tokens` here is a raw int (D-02/D-04). Two shapes for the same
 * daily-series concept now exist in the codebase on purpose -- do not "helpfully" merge them.
 */
export interface ProgramTokenPointData {
  date: string;
  /** Raw token total for this day, not pre-formatted (D-04) -- frontend owns magnitude formatting. */
  tokens: number;
}

/**
 * Mirrors backend `ProgramTokenTrendResponse`. Deliberately NOT `personal_usage`'s
 * `DailyTokenSeries` -- that sibling's `period_total`/`avg_per_day` are pre-formatted
 * strings; both are raw ints here (D-02/D-03/D-04). `avg_per_day` divides by the range's
 * fixed day-count, not the count of days with data (D-03).
 */
export interface ProgramTokenTrendData {
  points: ProgramTokenPointData[];
  /** Raw sum of tokens across the range, not pre-formatted (D-04). */
  period_total: number;
  /** Raw average tokens per day across the range (fixed day-count divisor, D-03), not pre-formatted (D-04). */
  avg_per_day: number;
}

/**
 * `fetchProgramTokenTrend()`'s result. Mirrors `ProgramDetailResult`'s (`@/types/programDetail`)
 * status vocabulary.
 */
export type ProgramTokenTrendResult =
  | { status: "ok"; data: ProgramTokenTrendData }
  | { status: "not_found" }
  | { status: "unauthorized" }
  | { status: "error" };
