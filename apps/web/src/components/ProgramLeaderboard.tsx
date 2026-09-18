import type { ProgramBoardCardData } from "@/types/programBoard";
import { ProgramCard } from "./ProgramCard";
import styles from "./ProgramLeaderboard.module.css";

const LOADING_PLACEHOLDER_COUNT = 6;

/**
 * "Program board — all programs using Harness" section (OVW-04-AC-1/AC-5,
 * DESIGN.md § Region — `PROGRAM LEADERBOARD`).
 *
 * The rendered heading is "Program board", not "leaderboard" — the mockup's
 * section *comment* says `PROGRAM LEADERBOARD`, but its rendered text is
 * "Program board" (DESIGN.md note 1); render the mockup's text. The heading
 * dot is `#c08a1e`, distinct from `OrgSummaryCards`' `#2a6fdb` dot — each
 * section owns its own dot colour. The right slot (DESIGN.md L502) is an
 * empty, styled `<div>` with no binding — `CLAUDE.md` § Design system
 * forbids inventing a control (count/filter/sort/pager) for it.
 *
 * Populated: `.map()`s `items` in the exact backend order (`tokens DESC` —
 * order is the contract, never re-sorted here), rendering one `ProgramCard`
 * per entry inside the `14px`-gap vertical stack (DESIGN.md § List
 * construct — a stack, not a grid).
 *
 * Loading: exactly `LOADING_PLACEHOLDER_COUNT` (6) skeleton cards regardless
 * of `page_size` — the mockup's `hint-placeholder-count="6"` is a loading
 * contract, not a sample-size promise (PO resolution #4). Do NOT render 20.
 *
 * Empty (`items: []`, AC-5/FR-4): the section header still renders; the card
 * stack is simply empty. The mockup has no empty-state variant and no copy
 * for one — none is invented here (DESIGN.md § States).
 *
 * No pager, no result count, no "load more" — the mockup shows none, and the
 * API's `page`/`page_size`/`total` remain a wire-level affordance only (PO
 * resolution #3). This section always renders page 1.
 */
export function ProgramLeaderboard({
  state,
  items,
}: {
  state: "populated" | "loading";
  items?: ProgramBoardCardData[];
}) {
  return (
    <section>
      <div className={styles.heading}>
        <span className={styles.dot} />
        <span className={styles.title}>Program board</span>
        <span className={styles.suffix}>— all programs using Harness</span>
        <div className={styles.rightSlot} />
      </div>
      <div className={styles.stack}>
        {state === "loading"
          ? Array.from({ length: LOADING_PLACEHOLDER_COUNT }).map(
              (_, index) => (
                <div
                  key={index}
                  className={styles.cardPlaceholder}
                  data-testid="program-leaderboard-card-placeholder"
                />
              ),
            )
          : (items ?? []).map((card) => (
              <ProgramCard key={card.program_id} card={card} />
            ))}
      </div>
    </section>
  );
}
