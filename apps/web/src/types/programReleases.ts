/**
 * `program-releases-api` wire shapes (PGD-03, DECISIONS.md D-02).
 */

/**
 * Mirrors backend `ProgramReleaseItem` (`services/api/app/schemas/program_releases.py`).
 * All fields are strings, pre-formatted by the producer -- no per-row `tagColor`/`tagBg`;
 * those are hoisted to `ProgramReleasesData` (D-02).
 */
export interface ProgramReleaseItemData {
  ver: string;
  label: string;
  dot: string;
  date: string;
  stories: string;
  prs: string;
}

/**
 * Mirrors backend `ProgramReleasesResponse`. `tagColor`/`tagBg` are program-level constants
 * (identical across every item in `items`), hoisted to the top level rather than repeated
 * per row (D-02) -- NOT `total_count`, `relTotal` is the PRD's own literal field name.
 */
export interface ProgramReleasesData {
  items: ProgramReleaseItemData[];
  relTotal: string;
  tagColor: string;
  tagBg: string;
}

/**
 * `fetchProgramReleases()`'s result. Mirrors `ProgramDetailResult`'s (`@/types/programDetail`)
 * / `ProgramTokenTrendResult`'s (`@/types/programTokenTrend`) status vocabulary.
 */
export type ProgramReleasesResult =
  | { status: "ok"; data: ProgramReleasesData }
  | { status: "not_found" }
  | { status: "unauthorized" }
  | { status: "error" };
