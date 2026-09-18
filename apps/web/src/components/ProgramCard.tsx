import type { ProgramBoardCardData } from "@/types/programBoard";
import { getProgramStyle } from "@/lib/programStyle";
import { momChipStyle } from "@/lib/momChipStyle";
import { ProgramSparkline } from "@/components/ProgramSparkline";
import { ProgramCardLink } from "./ProgramCardLink";
import styles from "./ProgramCard.module.css";

/**
 * One program board card (OVW-04-AC-1/AC-3/AC-4, DESIGN.md § Card root /
 * Top row / Body grid).
 *
 * The whole card is a single `<a href={card.href}>` — the navigation
 * affordance (AC-3). `href` is consumed verbatim from the API, never
 * reconstructed client-side (R-06). `avatarStyle`/`typeChip` come from
 * `getProgramStyle(type)` (D-04) — `icon` itself ships on the wire verbatim
 * (D-04, NOT derived here). The MoM chip's colors come from
 * `momChipStyle(mom_direction)`; a `null` result means the chip is omitted
 * entirely (FR-3 neutral state, <2 sparkline points).
 *
 * `metrics` renders in the server-given order — exactly 4 boxes, `glyph`
 * and `label` read from the wire, never hardcoded (AC-4/R-08). Repos
 * progress (`repoLabel`, fill %) is composed client-side from the two raw
 * ints, with a `total === 0` guard rendering `0 / 0` and a 0%-width fill
 * (DESIGN.md § Repos-with-Harness progress).
 *
 * This component itself is a Server Component — the root `<a>` and its
 * D-06 click telemetry live in `ProgramCardLink.tsx`, the one `"use client"`
 * leaf, so the rest of the card (including `ProgramSparkline`'s SVG
 * rendering and the style lookups below) is never shipped to the browser
 * bundle. See `ProgramCardLink.tsx` for why.
 */
export function ProgramCard({ card }: { card: ProgramBoardCardData }) {
  const { avatarStyle, typeChip } = getProgramStyle(card.type);
  const chipStyle = momChipStyle(card.sparkline.mom_direction);

  const installed = card.repos_with_harness_installed;
  const total = card.repos_total;
  const repoLabel = `${installed} / ${total}`;
  const repoPct = total === 0 ? 0 : Math.round((installed / total) * 100);

  return (
    <ProgramCardLink
      href={card.href}
      programId={card.program_id}
      borderLeftColor={avatarStyle.color as string}
      ariaLabel={`${card.name} — open program detail`}
    >
      <div className={styles.topRow}>
        <div className={styles.avatar} style={avatarStyle}>
          {card.icon}
        </div>
        <div className={styles.identity}>
          <div className={styles.titleRow}>
            <span className={styles.name}>{card.name}</span>
            <span className={styles.typeChip} style={typeChip}>
              {card.type}
            </span>
          </div>
          <div className={styles.description}>{card.description}</div>
        </div>
        <span className={styles.navGlyph} aria-hidden="true">
          →
        </span>
      </div>

      <div className={styles.bodyGrid}>
        <div className={styles.sparklinePanel}>
          <div className={styles.sparklineHeader}>
            <span className={styles.panelLabel}>Monthly token consumption</span>
            {chipStyle ? (
              <span
                className={styles.momChip}
                style={chipStyle}
                aria-label={momAriaLabel(
                  card.sparkline.mom_direction,
                  card.sparkline.mom_change_percent,
                )}
              >
                {momGlyphLabel(
                  card.sparkline.mom_direction,
                  card.sparkline.mom_change_percent,
                )}
              </span>
            ) : null}
          </div>
          <div className={styles.chartSlot}>
            <ProgramSparkline
              points={card.sparkline.points}
              typeColor={avatarStyle.color as string}
            />
          </div>
        </div>

        <div className={styles.metricsColumn}>
          <div className={styles.metricGrid}>
            {card.metrics.map((metric, index) => (
              <div className={styles.metricBox} key={index}>
                <div className={styles.metricIconLabel}>
                  <span className={styles.metricIcon}>{metric.glyph}</span>
                  <span className={styles.metricLabel}>{metric.label}</span>
                </div>
                <div className={styles.metricValue}>{metric.value}</div>
              </div>
            ))}
          </div>

          <div className={styles.reposBlock}>
            <div className={styles.reposHeader}>
              <span className={styles.panelLabel}>Repos with Harness installed</span>
              <span className={styles.repoLabel}>{repoLabel}</span>
            </div>
            <div className={styles.track}>
              <div
                className={styles.fill}
                style={{ width: `${repoPct}%`, background: avatarStyle.color }}
              />
            </div>
          </div>
        </div>
      </div>
    </ProgramCardLink>
  );
}

/** `▲`/`▼`/`—` per DESIGN.md § MoM change indicator — glyph carries the
 * direction, not color alone (non-colour-reliant NFR). `null` direction is
 * handled by the caller (chip omitted entirely). */
function momGlyphLabel(
  direction: "up" | "down" | "flat" | null,
  pct: number | null,
): string {
  const magnitude = pct === null ? 0 : Math.abs(pct);
  if (direction === "up") return `▲ ${magnitude}%`;
  if (direction === "down") return `▼ ${magnitude}%`;
  return `— ${magnitude}%`;
}

/** Accessible equivalent for the glyph-encoded chip — `▲`/`▼`/`—` have no
 * reliable screen-reader pronunciation (DESIGN.md § Keyboard and assistive
 * tech). */
function momAriaLabel(
  direction: "up" | "down" | "flat" | null,
  pct: number | null,
): string {
  const magnitude = pct === null ? 0 : Math.abs(pct);
  if (direction === "up") return `up ${magnitude} percent`;
  if (direction === "down") return `down ${magnitude} percent`;
  return `flat ${magnitude} percent`;
}
