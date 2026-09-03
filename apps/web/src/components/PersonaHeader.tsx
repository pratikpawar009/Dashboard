import type { Persona } from "@/types/persona";
import { formatPersonaTag, PersonaTagError } from "@/lib/formatPersonaTag";
import styles from "./PersonaHeader.module.css";

/**
 * Persona-context header: renders the persona tag pill + its
 * persona-specific subtitle (FR-2), or — when `persona` is not one of the
 * 4 valid personas (this covers `'cio'` and any persona-resolver error
 * sentinel alike, per D-03) — a neutral "Persona unavailable" badge plus a
 * visually-hidden `aria-live="assertive"` announcement (FR-5).
 *
 * `persona` is guaranteed defined here: `PersonaDashboardShell` only mounts
 * this component once its own loading gate (`persona !== undefined`) has
 * passed (T-10) — this component has no loading state of its own. Any
 * error other than `PersonaTagError` propagates uncaught rather than being
 * folded into the neutral badge.
 */
export function PersonaHeader({ persona }: { persona: Persona }) {
  try {
    const { tag, subtitle, color, background } = formatPersonaTag(persona);
    return (
      <div className={styles.header}>
        <span className={styles.pill} style={{ color, background }}>
          {tag}
        </span>
        {subtitle}
      </div>
    );
  } catch (error) {
    if (!(error instanceof PersonaTagError)) {
      throw error;
    }
    return (
      <div className={styles.header}>
        <span className={`${styles.pill} ${styles.pillNeutral}`}>
          Persona unavailable
        </span>
        <span aria-live="assertive" className={styles.visuallyHidden}>
          Unable to load your dashboard view.
        </span>
      </div>
    );
  }
}
