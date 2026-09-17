/**
 * `program-session-series-api` wire shapes (PGD-06, DECISIONS.md D-01/D-02/D-03/D-04).
 */

/**
 * Mirrors backend `SessionPoint` (`services/api/app/schemas/program_session_series.py`).
 */
export interface SessionPointData {
  date: string;
  /** Raw session-time total for this day, in seconds, not pre-formatted (D-04) -- frontend owns h/m formatting. */
  session_time_seconds: number;
}

/**
 * Mirrors backend `SessionSeriesResponse`. All three numeric fields are raw ints (seconds),
 * never pre-formatted duration strings (D-04). `avg_seconds_per_day` divides by the range's
 * fixed day-count, not the count of days with data (D-03).
 */
export interface SessionSeriesData {
  points: SessionPointData[];
  /** Raw sum of session-time seconds across the range, not pre-formatted (D-04). */
  period_total_seconds: number;
  /** Raw average session-time seconds per day across the range (fixed day-count divisor, D-03), not pre-formatted (D-04). */
  avg_seconds_per_day: number;
}

/**
 * `fetchProgramSessionSeries()`'s result. `denied` is kept distinct from `error`
 * (AF-01, story AC-5) -- a `403` from `member_in_program_visibility` is a denial of a
 * non-self `member_id`, not a transient failure, so a consumer can tell "you may not view
 * this member" from "the upstream is down" and offer no retry on the former. This follows
 * `MemberUsageResult` (`@/types/memberUsage`, PGD-05), the only other route that can 403 for
 * this reason, rather than `ProgramTokenTrendResult`, whose upstream cannot 403 and which
 * therefore has no `denied` member.
 *
 * There is deliberately no `not_found`: this route never returns `404` -- an unknown
 * `program_id` responds `200` with an all-zero series (PGD-06-FR-3).
 */
export type SessionSeriesResult =
  | { status: "ok"; data: SessionSeriesData }
  | { status: "denied" }
  | { status: "unauthorized" }
  // `invalid_range` (AF-05) is kept distinct from `error`: the API returns an explicit
  // `400 invalid_range` for a range outside {7d,30d,90d}, and collapsing that into a
  // generic failure reports a caller mistake as an upstream outage.
  | { status: "invalid_range" }
  | { status: "error" };
