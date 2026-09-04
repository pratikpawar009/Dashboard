import type { ProgramSummaryCardData } from "@/types/programDetail";
import styles from "./ProgramSummaryCards.module.css";

const LOADING_PLACEHOLDER_COUNT = 7;

/**
 * "Program summary — to date" 7-card grid (AC-3, DESIGN.md Region 4).
 *
 * Populated: `.map()`s over `cards` in the exact order the backend returns
 * (D-06/ADR-0007 — order is the contract; never re-sorted or re-indexed
 * here). Each card's `glyph`/`value`/`label` render verbatim — values arrive
 * pre-formatted server-side, so no client-side number formatting happens in
 * this component.
 *
 * Loading: renders `LOADING_PLACEHOLDER_COUNT` (7 — the mockup's own
 * `hint-placeholder-count="7"`, a contract, not a sample size) placeholder
 * cards at the same card geometry with text suppressed.
 *
 * "— to date" is static copy (DESIGN.md Region 4) — there is no range
 * toggle and no as-of timestamp anywhere in this story; the heading never
 * varies with props.
 */
export function ProgramSummaryCards({
  state,
  cards,
}: {
  state: "populated" | "loading";
  cards?: ProgramSummaryCardData[];
}) {
  return (
    <section>
      <div className={styles.heading}>
        <span className={styles.dot} />
        <span className={styles.title}>Program summary</span>
        <span className={styles.toDate}>— to date</span>
      </div>
      <div className={styles.grid}>
        {state === "loading"
          ? Array.from({ length: LOADING_PLACEHOLDER_COUNT }).map(
              (_, index) => (
                <div
                  key={index}
                  className={styles.card}
                  data-testid="program-summary-card-placeholder"
                />
              ),
            )
          : (cards ?? []).map((card, index) => (
              <div
                key={index}
                className={styles.card}
                data-testid="program-summary-card"
              >
                <div className={styles.glyph}>{card.glyph}</div>
                <div className={styles.value}>{card.value}</div>
                <div className={styles.label}>{card.label}</div>
              </div>
            ))}
      </div>
    </section>
  );
}
