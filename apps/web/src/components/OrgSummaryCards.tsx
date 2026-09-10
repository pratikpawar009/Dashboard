import type { OrgSummaryCardData } from "@/types/overview";
import styles from "./OrgSummaryCards.module.css";

const LOADING_PLACEHOLDER_COUNT = 5;

/**
 * "Organization summary — all programs · To date" 5-card grid (AC-5,
 * DESIGN.md Region 1).
 *
 * Populated: `.map()`s over `cards` in the exact order the backend returns
 * (order is the contract — never re-sorted or re-indexed here). Each card's
 * `glyph`/`value`/`label` render verbatim — values arrive pre-formatted
 * server-side, so no client-side number formatting happens in this
 * component. `sub` renders only when truthy (DESIGN.md's
 * `<sc-if value="{{ k.sub }}">` guard) — a falsy `sub` omits the element
 * entirely, it is never rendered empty. Today only card 1 ships a non-null
 * `sub` (DECISIONS.md D-02); the component itself makes no assumption about
 * which index that is.
 *
 * Loading: renders `LOADING_PLACEHOLDER_COUNT` (5 — the mockup's own
 * `hint-placeholder-count="5"`, a contract, not a sample size) placeholder
 * cards at the same card geometry with text suppressed.
 *
 * "Organization summary" + "— all programs · To date" are static copy
 * (DESIGN.md Region 1) — there is no range toggle and no as-of timestamp
 * anywhere in this story (AC-6 is backend-only); the heading never varies
 * with props, matching `ProgramSummaryCards.tsx`'s own "— to date"
 * precedent.
 */
export function OrgSummaryCards({
  state,
  cards,
}: {
  state: "populated" | "loading";
  cards?: OrgSummaryCardData[];
}) {
  return (
    <section>
      <div className={styles.heading}>
        <span className={styles.dot} />
        <span className={styles.title}>Organization summary</span>
        <span className={styles.suffix}>— all programs · To date</span>
      </div>
      <div className={styles.grid}>
        {state === "loading"
          ? Array.from({ length: LOADING_PLACEHOLDER_COUNT }).map(
              (_, index) => (
                <div
                  key={index}
                  className={styles.card}
                  data-testid="org-summary-card-placeholder"
                />
              ),
            )
          : (cards ?? []).map((card, index) => (
              <div
                key={index}
                className={styles.card}
                data-testid="org-summary-card"
              >
                <div className={styles.glyph}>{card.glyph}</div>
                <div>
                  <div className={styles.value}>{card.value}</div>
                  <div className={styles.label}>{card.label}</div>
                  {card.sub ? (
                    <div
                      className={styles.sub}
                      data-testid="org-summary-card-sub"
                    >
                      {card.sub}
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
      </div>
    </section>
  );
}
