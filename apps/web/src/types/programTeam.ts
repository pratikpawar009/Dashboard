/**
 * `program-team-api` wire shapes (PGD-05, PGD-05-FR-2).
 */

/**
 * Mirrors backend `ProgramTeamRow` (`services/api/app/schemas/program_detail.py`), field order
 * locked per FR-2/D-06. `sessions`, `tokens`, `avg_tokens_per_session` are RAW ints -- mirrors
 * `ProgramTokenTrendData`'s (`@/types/programTokenTrend`) numeric fields, NOT
 * `programReleases.ts`'s pre-formatted strings; the renderer owns M/K/B magnitude formatting.
 *
 * `member_id` (D-06) is the roster identity id (`program_members.user_id`) -- the stable
 * identifier the member-usage popup addresses, distinct from `member_name` which is
 * display-only.
 */
export interface ProgramTeamRowData {
  member_id: string;
  member_name: string;
  role: string;
  sessions: number;
  tokens: number;
  avg_tokens_per_session: number;
}

/**
 * Mirrors backend `ProgramTeamResponse`. `items` excludes any roster member with zero
 * in-range activity (active-in-range contract) -- zero active members yields `{items: []}`.
 */
export interface ProgramTeamData {
  items: ProgramTeamRowData[];
}

/**
 * `fetchProgramTeam()`'s result. Mirrors `ProgramDetailResult`'s (`@/types/programDetail`)
 * / `ProgramCommandsResult`'s (`@/types/programCommands`) status vocabulary. No `not_found`
 * variant -- this route never 404s on an unknown `program_id`.
 */
export type ProgramTeamResult =
  | { status: "ok"; data: ProgramTeamData }
  | { status: "unauthorized" }
  | { status: "error" };
