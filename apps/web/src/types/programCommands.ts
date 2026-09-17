/**
 * `program-commands-api` wire shapes (PGD-04, DECISIONS.md D-04), reused from
 * `personal-usage-api` per D-03.
 */

/**
 * Mirrors backend `CommandEntry` (`services/api/app/schemas/personal_usage.py`), imported
 * verbatim into `program_commands.py` per D-03 -- no separate `program_commands` schema module
 * exists. `count` is a raw int -- the deliberate exception to this response's otherwise
 * pre-formatted fields; `barStyle` is a ready-to-bind CSS width string, max-of-range not
 * share-of-total.
 */
export interface ProgramCommandEntryData {
  command: string;
  count: number;
  barStyle: string;
}

/**
 * Mirrors backend `CommandsPanel`. `total_runs` is snake_case on the wire and pre-formatted --
 * do not normalize to camelCase or to a number.
 */
export interface ProgramCommandsData {
  total_runs: string;
  items: ProgramCommandEntryData[];
}

/**
 * `fetchProgramCommands()`'s result. Mirrors `ProgramDetailResult`'s (`@/types/programDetail`)
 * / `ProgramTokenTrendResult`'s (`@/types/programTokenTrend`) status vocabulary. `not_found` is
 * kept for union-exhaustiveness with the shared proxy pattern even though this endpoint never
 * returns it (D-02 -- unknown/quiet `program_id` returns `200 {total_runs: "0", items: []}`).
 */
export type ProgramCommandsResult =
  | { status: "ok"; data: ProgramCommandsData }
  | { status: "not_found" }
  | { status: "unauthorized" }
  | { status: "error" };
