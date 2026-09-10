import styles from "./OverviewErrorPanel.module.css";

/**
 * D-07 generic fallback panel -- one message for `forbidden` / `unauthorized`
 * / `error` alike (`OverviewSummaryResult`, `@/types/overview`). Deliberately
 * does not branch copy per status: distinguishing "forbidden" from
 * "unauthorized" in user-facing text would leak whether the resource exists
 * and whether the viewer's own session is the problem (the same reasoning
 * `.claude/rules/security-baseline.md` applies to 404-over-403 for
 * foreign-owned resources).
 *
 * Mirrors `ProgramDetailErrorPanel`'s own precedent: takes no props (an
 * optional `status` is accepted but ignored for copy purposes, so a caller
 * can pass the failing `OverviewSummaryResult["status"]` for context without
 * it ever affecting the rendered message), and owns a self-contained
 * card-recipe `.module.css` (`docs/design/tokens.md` § Card recipe) rather
 * than importing another component's styles.
 *
 * Rendered by `AdoptionOverview` (T-13) *instead of*, never alongside,
 * `OrgSummaryCards`/`AdoptionIndicator`.
 */
export interface OverviewErrorPanelProps {
  status?: "forbidden" | "unauthorized" | "error";
}

export function OverviewErrorPanel(props: OverviewErrorPanelProps = {}) {
  // `status` is accepted for caller context only -- D-07 is one message for
  // every non-ok status, so it is intentionally never read here.
  void props;
  return (
    <div className={styles.panel}>
      <p className={styles.message}>You don&apos;t have access to this view.</p>
    </div>
  );
}
