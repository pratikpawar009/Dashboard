import type { ProgramsUsingAiData } from "@/types/overview";
import styles from "./AdoptionIndicator.module.css";

// DECISIONS.md D-06: `#2a6fdb` is the existing Primary/brand token
// (docs/design/tokens.md § Color); `#dfe3e9`/`#c3c9d2` are new, added to
// tokens.md's Color table by this same task (T-11).
const ADOPTED_COLOR = "#2a6fdb";
const NOT_ADOPTED_BAR_COLOR = "#dfe3e9";
const NOT_ADOPTED_LEGEND_COLOR = "#c3c9d2";

export interface AdoptionIndicatorProps {
  state: "populated" | "loading";
  data?: ProgramsUsingAiData;
}

/**
 * "Adoption Level" indicator (DESIGN.md Region 2 — this is the rendered
 * heading text; the section's mockup *comment* is "PROGRAM ADOPTION
 * HEALTH", which is never shown to a user).
 *
 * Headline and subtitle are composed client-side from the raw
 * `count`/`total`/`adoption_percent` on `ProgramsUsingAiData`
 * (DECISIONS.md D-05) — the backend ships these raw rather than a
 * pre-formatted headline string because the same numbers also drive
 * `OrgSummaryCards`' first card.
 *
 * Bar segment widths and legend swatch colors are derived client-side
 * (DECISIONS.md D-06, `OVW-01-FR-2`: no inline CSS crosses the wire) —
 * `#2a6fdb` (existing brand token) for "Using AI SDLC", and two new tokens
 * for "Not yet adopted": `#dfe3e9` for the bar segment, `#c3c9d2` for the
 * legend swatch (deliberately different colors for the same semantic,
 * matching the mockup's own embedded script).
 *
 * `adoption_percent === null` (never `0`) is the zero-state signal
 * (`OVW-01-FR-4`, `programs_total === 0`): literal "0/0" headline (no
 * spaces), subtitle with the percent clause omitted entirely, a single
 * flat not-adopted-colored bar segment (no adopted/not-adopted split), and
 * both legend entries at 0. The branch below narrows on
 * `adoption_percent === null` directly — never a `percent ?? 0` /
 * `percent || 0` fallback, which would silently collapse the null/zero
 * distinction the backend goes out of its way to preserve.
 *
 * Loading: skeleton geometry (bar + the fixed 2-entry legend shape), all
 * text suppressed.
 */
export function AdoptionIndicator({ state, data }: AdoptionIndicatorProps) {
  if (state === "loading") {
    return (
      <section className={styles.section}>
        <div className={styles.heading}>
          <span className={styles.dot} />
          <span className={styles.title}>Adoption Level</span>
        </div>
        <div className={styles.bar} data-testid="adoption-bar-placeholder">
          <div className={styles.barSegmentPlaceholder} />
        </div>
        <div className={styles.legend}>
          <div
            className={styles.legendEntryPlaceholder}
            data-testid="adoption-legend-placeholder"
          />
          <div
            className={styles.legendEntryPlaceholder}
            data-testid="adoption-legend-placeholder"
          />
        </div>
      </section>
    );
  }

  // Defensive default for a missing `data` prop in the "populated" state --
  // mirrors the zero-state shape exactly, so a missing prop falls into the
  // zero-state branch below rather than computing against `undefined`.
  const { count, total, adoption_percent } = data ?? {
    count: 0,
    total: 0,
    adoption_percent: null,
  };

  if (adoption_percent === null) {
    return (
      <section className={styles.section}>
        <div className={styles.heading}>
          <span className={styles.dot} />
          <span className={styles.title}>Adoption Level</span>
        </div>
        <div className={styles.headline} data-testid="adoption-headline">
          0/0
        </div>
        <div className={styles.subtitle} data-testid="adoption-subtitle">
          programs using AI SDLC
        </div>
        <div className={styles.bar} data-testid="adoption-bar">
          <div
            className={styles.barSegment}
            data-testid="adoption-bar-segment"
            style={{ width: "100%", backgroundColor: NOT_ADOPTED_BAR_COLOR }}
          />
        </div>
        <ul className={styles.legend}>
          <li
            className={styles.legendEntry}
            data-testid="adoption-legend-entry"
          >
            <span
              className={styles.legendSwatch}
              style={{ backgroundColor: ADOPTED_COLOR }}
            />
            <span className={styles.legendCount}>0</span>
            <span className={styles.legendLabel}>Using AI SDLC</span>
          </li>
          <li
            className={styles.legendEntry}
            data-testid="adoption-legend-entry"
          >
            <span
              className={styles.legendSwatch}
              style={{ backgroundColor: NOT_ADOPTED_LEGEND_COLOR }}
            />
            <span className={styles.legendCount}>0</span>
            <span className={styles.legendLabel}>Not yet adopted</span>
          </li>
        </ul>
      </section>
    );
  }

  const notAdoptedCount = total - count;

  return (
    <section className={styles.section}>
      <div className={styles.heading}>
        <span className={styles.dot} />
        <span className={styles.title}>Adoption Level</span>
      </div>
      <div className={styles.headline} data-testid="adoption-headline">
        {`${count} / ${total}`}
      </div>
      <div className={styles.subtitle} data-testid="adoption-subtitle">
        {`programs using AI SDLC · ${Math.round(adoption_percent)}% of the org`}
      </div>
      <div className={styles.bar} data-testid="adoption-bar">
        <div
          className={styles.barSegment}
          data-testid="adoption-bar-segment"
          style={{
            width: `${adoption_percent}%`,
            backgroundColor: ADOPTED_COLOR,
          }}
        />
        <div
          className={styles.barSegment}
          data-testid="adoption-bar-segment"
          style={{
            width: `${100 - adoption_percent}%`,
            backgroundColor: NOT_ADOPTED_BAR_COLOR,
          }}
        />
      </div>
      <ul className={styles.legend}>
        <li className={styles.legendEntry} data-testid="adoption-legend-entry">
          <span
            className={styles.legendSwatch}
            style={{ backgroundColor: ADOPTED_COLOR }}
          />
          <span className={styles.legendCount}>{count}</span>
          <span className={styles.legendLabel}>Using AI SDLC</span>
        </li>
        <li className={styles.legendEntry} data-testid="adoption-legend-entry">
          <span
            className={styles.legendSwatch}
            style={{ backgroundColor: NOT_ADOPTED_LEGEND_COLOR }}
          />
          <span className={styles.legendCount}>{notAdoptedCount}</span>
          <span className={styles.legendLabel}>Not yet adopted</span>
        </li>
      </ul>
    </section>
  );
}
