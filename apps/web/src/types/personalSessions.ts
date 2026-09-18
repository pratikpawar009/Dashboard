/**
 * `personal-sessions-api` wire shapes (SHP-03-FR-1). Mirrors
 * `services/api/app/schemas/personal_sessions.py` field-for-field -- the two must not drift.
 */

/**
 * Mirrors backend `PersonalSessionEntry` (4 fields, all pre-formatted strings, `extra="forbid"`
 * server-side, DECISIONS.md D-03). `meta` is a server-composed pre-joined string
 * (e.g. `"S-1088 · Jul 5, 2026"`) -- there is no separate `session_identifier`/`started_at` field.
 */
export interface PersonalSessionEntryData {
  title: string;
  meta: string;
  duration: string;
  tokens: string;
}

/**
 * Mirrors backend `PersonalSessionsResponse` envelope. `page`/`page_size`/`total` are RAW ints --
 * mirrors `ProgramTeamRowData`'s (`@/types/programTeam`) raw-int precedent, not
 * `ProgramSummaryCard`'s pre-formatted-string one. Field names are kept snake_case verbatim to
 * mirror the backend wire shape, matching this directory's existing convention (e.g.
 * `programTeam.ts`'s `avg_tokens_per_session`, `memberUsage.ts`'s `daily_tokens`/`period_total`) --
 * no camelCase reshaping happens client-side.
 */
export interface PersonalSessionsData {
  items: PersonalSessionEntryData[];
  page: number;
  page_size: number;
  total: number;
}

/**
 * `fetchPersonalSessions()`'s result. Mirrors `MemberUsageResult`'s (`@/types/memberUsage`)
 * status vocabulary: `denied` is kept distinct from `error` since this route sits behind the same
 * `individual_usage_visibility` self-or-cio gate family (self always, else `cio` only) -- a 403 is
 * a denial, not a transient failure. No `not_found` variant -- no `program_id`/route param this
 * route can 404 on beyond auth. No `invalid_range` variant -- this route paginates via
 * `page`/`page_size`, not a `?range` query param.
 */
export type PersonalSessionsResult =
  | { status: "ok"; data: PersonalSessionsData }
  | { status: "denied" }
  | { status: "unauthorized" }
  | { status: "error" };
