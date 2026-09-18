/**
 * `artifacts-api` wire shapes (SHP-04-FR-1). Mirrors
 * `services/api/app/schemas/artifacts.py` field-for-field -- the two must not
 * drift.
 */

/**
 * One canonical artifact type row (SHP-04-FR-1). `tag`/`name`/`bg`/`color` are
 * server-owned presentation constants -- never derived client-side. `count`
 * is a raw int, mirroring `ProgramTeamRowData`'s (`@/types/programTeam`)
 * raw-int precedent, not `ProgramSummaryCard`'s pre-formatted-string one.
 */
export interface ArtifactItemData {
  tag: string;
  name: string;
  count: number;
  bg: string;
  color: string;
}

/**
 * Response envelope for `GET /api/artifacts/{program_id}`. `items` is always
 * exactly 5 entries in mockup order (`prd`, `user_story`, `test_case`,
 * `arch_diagram`, `api_spec`) -- a zero-count type still appears, never
 * omitted (AC-3). Kept as a plain array rather than a 5-tuple: TypeScript has
 * no ergonomic fixed-length-array literal that survives JSON round-tripping
 * without contorting every consumer (`items[0]`/`items[4]` indexing, or a
 * cast at the fetch boundary) -- a `ArtifactItemData[]` is simpler for
 * consumers that map over `items` (as the panel does), and the 5-entry
 * invariant is already enforced server-side (`ArtifactsResponse` docstring)
 * and exercised by TC-01/TC-03/TC-07/TC-08.
 */
export interface ArtifactsData {
  items: ArtifactItemData[];
}

/**
 * `fetchProgramArtifacts()`'s result. Mirrors `ProgramTeamResult`'s
 * (`@/types/programTeam`) status vocabulary: no `not_found` variant -- this
 * route never 404s on an unknown `program_id` (SHP-04-FR-3), and no
 * `invalid_range` variant either -- this route takes no `range` query param.
 */
export type ArtifactsResult =
  | { status: "ok"; data: ArtifactsData }
  | { status: "unauthorized" }
  | { status: "error" };
