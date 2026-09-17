"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { TokenAreaChart } from "@/components/DailyTokenTrendChart";
import { fetchMemberUsage } from "@/lib/memberUsageApi.client";
import { getAvatarBackground, getInitials } from "@/lib/teamAvatarStyle";
import type { MemberUsageData } from "@/types/memberUsage";

import styles from "./MemberUsagePopup.module.css";

type RangeKey = "7d" | "30d" | "90d";

const RANGE_OPTIONS: { key: RangeKey; label: string }[] = [
  { key: "7d", label: "7D" },
  { key: "30d", label: "30D" },
  { key: "90d", label: "90D" },
];

const RANGE_LABELS: Record<RangeKey, string> = {
  "7d": "last 7 days",
  "30d": "last 30 days",
  "90d": "last 90 days",
};

const DEFAULT_RANGE: RangeKey = "30d";

/** DESIGN.md § 2.4 Loading: 4 card placeholders, matching `cards`' fixed length. */
const CARD_PLACEHOLDER_COUNT = 4;
/** DESIGN.md § 2.4 Loading: "6 placeholder rows (hint-placeholder-count="6" from the ARC mockup)". */
const COMMAND_PLACEHOLDER_COUNT = 6;

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Member usage popup (Program Detail team table, PGD-05 T-16, DESIGN.md § Screen 2).
 *
 * Originated design -- no mockup backs this popup (DESIGN.md § Screen 2 provenance). Modal
 * chrome is EMD's popup reused verbatim with the deltas DESIGN.md § 2.2 names; content follows
 * the ARC "MY USAGE" contract (`personal-usage-api`, ADR-0009), rendered here via the T-14 proxy
 * (`fetchMemberUsage`) scoped by `member_in_program_visibility` rather than SHP-02's own
 * `individual_usage_visibility`.
 *
 * Renders all three `personal-usage-api` blocks (AC-9/AC-10/AC-11/AC-12 in full): the 4-card
 * row, the daily-tokens chart (AF-05 fix, 2026-09-17 -- `DailyTokenPoint` gained a raw
 * `tokens: int` per the ADR-0009 amendment, reusing `TokenAreaChart`'s shipped geometry at
 * 180px), and the commands list.
 *
 * `memberId` is `ProgramTeamRow.member_id` (D-06, `program_members.user_id`) -- the stable
 * roster identity id `member_in_program_visibility` and the usage endpoint require, distinct
 * from the display-only `memberName`.
 *
 * Dialog semantics (DESIGN.md § 2.2 Dialog semantics, all **[NEW]**): `role="dialog"` +
 * `aria-modal`, initial focus on the close button, a focus trap scoped to the panel, focus
 * restore to the triggering row button on dismiss, Esc/overlay-click/close-button dismissal,
 * `inert` on the page root while open, portal-mounted at `<body>` so `z-index:60` clears the
 * page's own stacking contexts.
 */
export function MemberUsagePopup({
  programId,
  memberId,
  memberName,
  role,
  triggerRef,
  onClose,
}: {
  programId: string;
  memberId: string;
  memberName: string;
  role: string;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
  onClose: () => void;
}) {
  const [range, setRange] = useState<RangeKey>(DEFAULT_RANGE);
  const [status, setStatus] = useState<"loading" | "ok" | "denied" | "error">("loading");
  const [data, setData] = useState<MemberUsageData | undefined>(undefined);

  const latestRequestId = useRef(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const headingId = "member-usage-popup-heading";
  const descriptionId = "member-usage-popup-description";

  function load(nextRange: RangeKey) {
    const requestId = ++latestRequestId.current;
    setStatus("loading");
    fetchMemberUsage(programId, memberId, nextRange).then((result) => {
      if (requestId !== latestRequestId.current) {
        return;
      }
      switch (result.status) {
        case "ok":
          setData(result.data);
          setStatus("ok");
          break;
        case "denied":
          setStatus("denied");
          break;
        default:
          setStatus("error");
      }
    });
  }

  useEffect(() => {
    load(range);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [programId, memberId, range]);

  // DESIGN.md § 2.2 Dialog semantics: initial focus on the close button,
  // background inertness, restore body scroll + focus on unmount.
  useEffect(() => {
    closeButtonRef.current?.focus();

    const root = document.getElementById("__next") ?? document.body.firstElementChild;
    const previousInert = root?.hasAttribute("inert") ?? false;
    root?.setAttribute("inert", "");
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const trigger = triggerRef.current;
    return () => {
      if (!previousInert) {
        root?.removeAttribute("inert");
      }
      document.body.style.overflow = previousOverflow;
      trigger?.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // DESIGN.md § 2.2: Esc dismisses; Tab/Shift-Tab trapped within the panel.
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) {
        return;
      }
      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
      if (focusable.length === 0) {
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const isLoading = status === "loading";
  const rangeLabel = RANGE_LABELS[range];
  const avatarBackground = getAvatarBackground(role);
  const initials = getInitials(memberName);
  // DESIGN.md § 2.5: no range for a denied view to scope; § 2.4 disables
  // (never hides) chips while loading so they remain a visible, inert affordance.
  const showRangeChips = status !== "denied";

  const content = (
    <div
      className={styles.overlay}
      onClick={onClose}
      data-testid="member-usage-overlay"
    >
      <div
        ref={panelRef}
        className={
          status === "denied" || status === "error"
            ? `${styles.panel} ${styles.panelCompact}`
            : styles.panel
        }
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        aria-describedby={descriptionId}
        onClick={(event) => event.stopPropagation()}
      >
        <div className={styles.header}>
          <span
            className={styles.headerAvatar}
            style={{ background: avatarBackground }}
            aria-hidden="true"
          >
            {initials}
          </span>
          <div className={styles.headerText}>
            <h2 id={headingId} className={styles.headerName}>
              {memberName}
            </h2>
            <div id={descriptionId} className={styles.headerSub}>
              {role} · usage · {rangeLabel}
            </div>
          </div>
          {showRangeChips && (
            <div
              className={styles.toggleTrack}
              role="group"
              aria-label="Select date range for member usage"
            >
              {RANGE_OPTIONS.map((option) => {
                const isActive = option.key === range;
                return (
                  <button
                    key={option.key}
                    type="button"
                    className={
                      isActive
                        ? `${styles.toggleButton} ${styles.toggleButtonActive}`
                        : styles.toggleButton
                    }
                    aria-pressed={isActive}
                    disabled={isLoading}
                    onClick={() => setRange(option.key)}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          )}
          <button
            ref={closeButtonRef}
            type="button"
            className={styles.closeButton}
            aria-label={`Close usage for ${memberName}`}
            onClick={onClose}
          >
            <span aria-hidden="true">&#10005;</span>
          </button>
        </div>

        {status === "denied" ? (
          <div className={styles.messageBody} role="status">
            <span className={styles.messageGlyph} aria-hidden="true">
              &#128274;
            </span>
            <div className={styles.messageHeadline}>
              You don&apos;t have access to this member&apos;s usage
            </div>
            <div className={styles.messageCopy}>
              Individual usage is visible to the member themselves and to CIO-level roles.
            </div>
          </div>
        ) : status === "error" ? (
          <div className={styles.messageBody} role="status">
            <span className={styles.messageGlyph} aria-hidden="true">
              &#9888;
            </span>
            <div className={styles.messageHeadline}>Couldn&apos;t load this member&apos;s usage</div>
            <div className={styles.messageCopy}>Something went wrong. Try again.</div>
            <button
              type="button"
              className={styles.retryButton}
              onClick={() => load(range)}
            >
              Retry
            </button>
          </div>
        ) : (
          <div className={styles.body} aria-busy={isLoading}>
            {/* Block 1 -- cards row (DESIGN.md § 2.3 Block 1) */}
            <div className={styles.cardsGrid}>
              {isLoading
                ? Array.from({ length: CARD_PLACEHOLDER_COUNT }).map((_, i) => (
                    <div
                      key={i}
                      className={styles.card}
                      data-testid="member-usage-card-skeleton"
                      aria-hidden="true"
                    >
                      <div className={styles.cardSkeletonGlyph} />
                      <div className={styles.cardSkeletonValue} />
                      <div className={styles.cardSkeletonLabel} />
                    </div>
                  ))
                : data?.cards.map((card, i) => (
                    <div className={styles.card} key={i} data-testid="member-usage-card">
                      <div
                        className={styles.cardGlyph}
                        style={{ background: card.iconBg, color: card.iconColor }}
                      >
                        {card.glyph}
                      </div>
                      <div className={styles.cardValue}>{card.value}</div>
                      <div className={styles.cardLabel}>{card.label}</div>
                    </div>
                  ))}
            </div>

            {/* Block 2 -- daily tokens chart (DESIGN.md § 2.3 Block 2, AF-05 fix).
                Reuses `TokenAreaChart`'s shipped geometry/visual language at
                180px (not a second chart implementation) via the ADR-0009
                amendment's raw `points[].tokens` field. `accentColor` reuses
                the header's already-resolved avatar colour -- this popup has
                no program-type colour to inherit, unlike
                `DailyTokenTrendChart`'s Program Detail mount. */}
            <section className={styles.chartSection}>
              <div className={styles.chartHeader}>
                <div>
                  <div className={styles.title}>Daily token consumption</div>
                  <div className={styles.subtitle}>
                    AI token usage per day · {rangeLabel}
                  </div>
                </div>
                <div className={styles.chartStatBlock}>
                  {!isLoading && data ? (
                    <>
                      <div className={styles.chartStatTotal}>
                        {data.daily_tokens.period_total}
                      </div>
                      <div className={styles.chartStatAvg}>
                        total · {data.daily_tokens.avg_per_day} / day avg
                      </div>
                    </>
                  ) : (
                    <div
                      className={styles.chartStatSkeleton}
                      data-testid="member-usage-chart-stat-skeleton"
                    />
                  )}
                </div>
              </div>
              <div className={styles.chartArea}>
                {isLoading || !data ? (
                  <div
                    className={styles.chartSkeleton}
                    data-testid="member-usage-chart-skeleton"
                    aria-hidden="true"
                  />
                ) : (
                  <TokenAreaChart
                    points={data.daily_tokens.points}
                    accentColor={avatarBackground}
                    height={180}
                  />
                )}
              </div>
            </section>

            {/* Block 3 -- commands list (DESIGN.md § 2.3 Block 3) */}
            <div className={styles.commandsCard}>
              <div className={styles.commandsHeader}>
                <div className={styles.title}>Commands</div>
                <div className={styles.subtitle}>
                  Activity by Claude Code command · {rangeLabel}
                </div>
              </div>
              {!isLoading && (
                <div className={styles.totalStrip}>
                  <span className={styles.totalFigure}>{data?.commands.total_runs}</span>
                  <span className={styles.totalCaption}>total runs</span>
                </div>
              )}
              <div className={styles.commandsList}>
                {isLoading
                  ? Array.from({ length: COMMAND_PLACEHOLDER_COUNT }).map((_, i) => (
                      <div
                        key={i}
                        className={styles.commandRow}
                        data-testid="member-usage-command-skeleton"
                        aria-hidden="true"
                      >
                        <div className={styles.commandSkeletonChip} />
                        <div className={styles.commandSkeletonBar} />
                      </div>
                    ))
                  : data && data.commands.items.length === 0 ? (
                      <div className={styles.emptyCommands}>
                        No commands run in this period.
                      </div>
                    ) : (
                      data?.commands.items.map((item, i) => (
                        <div className={styles.commandRow} key={`${item.command}-${i}`}>
                          <div className={styles.commandLine}>
                            <code className={styles.commandChip}>{item.command}</code>
                            <span className={styles.commandCount}>
                              {item.count}
                              <span className={styles.commandCountLabel}> runs</span>
                            </span>
                          </div>
                          <div className={styles.barTrack}>
                            <div className={styles.barFill} style={{ width: item.barStyle }} />
                          </div>
                        </div>
                      ))
                    )}
              </div>
            </div>
          </div>
        )}

        <span aria-live="polite" className={styles.visuallyHidden}>
          {status === "loading"
            ? `Loading usage for ${memberName}`
            : status === "denied"
              ? `You don't have access to this member's usage`
              : status === "error"
                ? `Failed to load usage for ${memberName}`
                : `Usage for ${memberName} updated for ${rangeLabel}`}
        </span>
      </div>
    </div>
  );

  return createPortal(content, document.body);
}
