import styles from "./ProgramDetailErrorPanel.module.css";

/**
 * D-03 404 fallback panel — reuses the card recipe verbatim
 * (`docs/design/tokens.md` § Card recipe) in place of `ProgramSummaryCards`
 * when `program-detail-api` returns 404 (AC-7).
 *
 * Rendered by `ProgramDetailView` (T-12) *instead of*, never alongside,
 * `ProgramSummaryCards` — this component takes no props and owns no other
 * state.
 */
export function ProgramDetailErrorPanel() {
  return (
    <div className={styles.panel}>
      <p className={styles.message}>This program could not be found.</p>
    </div>
  );
}
