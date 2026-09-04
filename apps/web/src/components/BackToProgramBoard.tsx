import Link from "next/link";

import { ADOPTION_OVERVIEW_ROUTE } from "@/lib/routes";
import styles from "./BackToProgramBoard.module.css";

/**
 * Back-to-board link (AC-4, DESIGN.md Region 1).
 *
 * Targets `ADOPTION_OVERVIEW_ROUTE` (D-02) — the Adoption Overview page
 * (OVW epic) has not shipped yet, so this 404s today by design; OVW-01
 * flips the one constant it imports, not this component.
 *
 * The `←` glyph is part of the label string, not a separate icon element
 * (DESIGN.md Region 1) — do not split it into an `<svg>`/icon component.
 */
export function BackToProgramBoard() {
  return (
    <Link href={ADOPTION_OVERVIEW_ROUTE} className={styles.link}>
      ← Back to program board
    </Link>
  );
}
