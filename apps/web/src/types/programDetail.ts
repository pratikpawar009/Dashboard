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
