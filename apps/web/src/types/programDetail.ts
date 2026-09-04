/**
 * `program-detail-api` wire shapes (ADR-0007, DECISIONS.md D-05/D-06) plus the
 * `/api/programs` switcher-list shape (ADR-0005).
 */

/**
 * Mirrors backend `ProgramDetailHeader` -- data only, no `avatarStyle`/
 * `typeChip` (D-05). Consumers derive those via
 * `apps/web/src/lib/programStyle.ts::getProgramStyle(type)`.
 */
export interface ProgramDetailHeaderData {
  icon: string;
  name: string;
  type: string;
  description: string;
}

/**
 * One of the 7 ordered summary cards (ADR-0007, D-06). All fields are
 * strings -- `value` arrives pre-formatted server-side (`format_number()` or
 * the card-4 ratio string); `glyph`/`label` are fixed presentation constants
 * owned by the producer.
 */
export interface ProgramSummaryCardData {
  glyph: string;
  value: string;
  label: string;
}

/**
 * Response envelope for `GET /api/overview/program-detail/{program_id}`.
 * `summary` is an ordered array -- order is the contract (ADR-0007), never
 * re-sorted by a consumer.
 */
export interface ProgramDetailData {
  header: ProgramDetailHeaderData;
  summary: ProgramSummaryCardData[];
}

/**
 * Switcher-list item for a single program, mirrors backend `ProgramEntry`
 * (ADR-0005). `dotStyle` is pre-formatted CSS shipped as data.
 */
export interface ProgramSwitcherEntry {
  program_id: string;
  label: string;
  href: string;
  dotStyle: string;
}

/**
 * `fetchProgramDetail()`'s result. Shared by `programDetailApi.ts` (server)
 * and `programDetailApi.client.ts` (client) so neither module keeps its own
 * copy (DECISIONS.md D-08) -- both `page.tsx` and `ProgramDetailView.tsx`
 * consume this discriminated union.
 *
 * `"unauthorized"` means the caller (a proxy route or `page.tsx`) already ran
 * `tokenStore.callWithAuth`'s retry-once and was still rejected -- it is a
 * terminal outcome, NOT a signal for client-side JS to retry the fetch again
 * (DECISIONS.md D-10).
 */
export type ProgramDetailResult =
  | { status: "ok"; data: ProgramDetailData }
  | { status: "not_found" }
  | { status: "unauthorized" }
  | { status: "error" };
