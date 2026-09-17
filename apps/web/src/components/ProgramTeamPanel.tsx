"use client";

import { useEffect, useRef, useState } from "react";

import type { ProgramTeamData, ProgramTeamRowData } from "@/types/programTeam";
import { fetchProgramTeam } from "@/lib/programTeamApi.client";
import { formatTokens } from "./DailyTokenTrendChart";
import { getAvatarBackground, getInitials } from "@/lib/teamAvatarStyle";
import { MemberUsagePopup } from "./MemberUsagePopup";

import styles from "./ProgramTeamPanel.module.css";

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

/** DESIGN.md § Row list: mockup's `hint-placeholder-count="7"` -- seven
 * skeleton rows for the loading state, matching `ReleasesList.tsx`'s
 * PLACEHOLDER_ROW_COUNT idiom at this panel's own documented count. */
const PLACEHOLDER_ROW_COUNT = 7;

/**
 * "Project team" panel (Program Detail, PGD-05 T-15, DESIGN.md § Screen 1).
 *
 * Right card of the `COMMANDS + TEAM` two-up section, below the releases
 * list -- mounted by `ProgramDetailView.tsx` alongside PGD-04's Commands
 * panel. Self-fetching client component, mirroring `ReleasesList`'s /
 * `DailyTokenTrendChart`'s range-state / fetch-guard idiom: owns its own
 * `range` state and range chips, independent of the other two panels'
 * switchers.
 *
 * Unlike both sibling panels, the header carries no total/aggregate value
 * (DESIGN.md § Header: "no total/aggregate value ... The panel shows rows
 * only").
 *
 * `sessions`/`tokens`/`avg_tokens_per_session` arrive as RAW ints
 * (`ProgramTeamRowData`, PGD-05-FR-2) -- this component owns M/K/B magnitude
 * formatting via `formatTokens` (`DailyTokenTrendChart.tsx`), reused
 * verbatim rather than re-implemented (DESIGN.md § Pre-formatted values,
 * reusability-baseline DRY).
 *
 * Fetches via `@/lib/programTeamApi.client`'s `fetchProgramTeam()`, the
 * client-side counterpart of `@/lib/programTeamApi`'s server-only version
 * (T-12) -- mirrors `ReleasesList`/`DailyTokenTrendChart`'s split (ADR-0008:
 * a client component never reaches FastAPI directly or holds a token).
 *
 * `avBg`/`initials` are absent from `ProgramTeamRowData` -- both are
 * derived client-side per row via `@/lib/teamAvatarStyle`
 * (`getAvatarBackground`/`getInitials`), not read off the API response
 * (DESIGN.md § "Avatar colour and initials -- not supplied by this story's
 * API").
 *
 * States (DESIGN.md § Row list / § Empty state): `loading` renders
 * `PLACEHOLDER_ROW_COUNT` skeleton rows (avatar + name/role/sessions/tokens/
 * avg placeholders), mirroring `ReleasesList`'s skeleton convention
 * verbatim; `error` replaces the row list with an inline retry, reusing
 * `ReleasesList`'s error-panel pattern; `empty` (zero active members in
 * range) renders the literal copy "No active members in this range." --
 * concrete data-shape handling, not the undesigned popup surface.
 *
 * Rows are interactive triggers for the per-member usage popup (T-16,
 * DESIGN.md § 2.1 -- design gate satisfied 2026-09-17). Each row is a native
 * `<button>` carrying `aria-haspopup="dialog"` and an explicit
 * `aria-label`; activating it opens `MemberUsagePopup`, passed `row.member_id`
 * (D-06) as the popup's identity argument -- `member_name` stays a display-only
 * field, never used for addressing.
 */
export function ProgramTeamPanel({ programId }: { programId: string }) {
  const [range, setRange] = useState<RangeKey>(DEFAULT_RANGE);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [data, setData] = useState<ProgramTeamData | undefined>(undefined);
  const [openMember, setOpenMember] = useState<ProgramTeamRowData | undefined>(undefined);
  const rowRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const activeTriggerRef = useRef<HTMLButtonElement | null>(null);

  const latestRequestId = useRef(0);

  function load(nextRange: RangeKey) {
    const requestId = ++latestRequestId.current;
    setStatus("loading");
    fetchProgramTeam(programId, nextRange).then((result) => {
      if (requestId !== latestRequestId.current) {
        return;
      }
      if (result.status === "ok") {
        setData(result.data);
        setStatus("ok");
      } else {
        setStatus("error");
      }
    });
  }

  useEffect(() => {
    load(range);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [programId, range]);

  const isLoading = status === "loading";
  const rangeLabel = RANGE_LABELS[range];
  const isEmpty = status === "ok" && data !== undefined && data.items.length === 0;

  return (
    <section className={styles.section}>
      <div className={styles.header}>
        <div>
          <div className={styles.title}>Project team</div>
          <div className={styles.subtitle}>Members & contribution · {rangeLabel}</div>
        </div>
        <div
          className={styles.toggleTrack}
          role="group"
          aria-label="Select date range for project team"
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
      </div>
      <div className={styles.columnHeaders} role="row">
        <span role="columnheader">Member</span>
        <span role="columnheader">Role</span>
        <span className={styles.alignRight} role="columnheader">
          Sessions
        </span>
        <span className={styles.alignRight} role="columnheader">
          Tokens
        </span>
        <span className={styles.alignRight} role="columnheader">
          Avg / session
        </span>
      </div>
      <div role="table" aria-label="Project team members and contribution">
        {status === "error" ? (
          <div className={styles.errorPanel} role="alert">
            <span>Couldn&apos;t load the project team.</span>
            <button
              type="button"
              className={styles.retryButton}
              onClick={() => load(range)}
            >
              Retry
            </button>
          </div>
        ) : isEmpty ? (
          <div className={styles.emptyPanel}>No active members in this range.</div>
        ) : status === "ok" && data ? (
          data.items.map((member, i) => {
            const rowKey = `${member.member_id}-${i}`;
            const displayName = member.member_name || "this member";
            const accessibleLabel = member.member_name
              ? `View usage for ${member.member_name}, ${member.role}`
              : "View usage for this member";
            return (
              <button
                type="button"
                key={rowKey}
                className={styles.row}
                aria-label={accessibleLabel}
                aria-haspopup="dialog"
                ref={(el) => {
                  if (el) {
                    rowRefs.current.set(rowKey, el);
                  } else {
                    rowRefs.current.delete(rowKey);
                  }
                }}
                onClick={() => {
                  activeTriggerRef.current = rowRefs.current.get(rowKey) ?? null;
                  setOpenMember(member);
                }}
              >
                <span className={styles.memberCell} role="cell">
                  <span
                    className={styles.avatar}
                    style={{ background: getAvatarBackground(member.role) }}
                    aria-hidden="true"
                  >
                    {getInitials(member.member_name)}
                  </span>
                  <span className={styles.memberName}>{displayName}</span>
                </span>
                <span className={styles.role} role="cell">
                  {member.role}
                </span>
                <span className={styles.alignRight} role="cell">
                  {String(member.sessions)}
                </span>
                <span className={`${styles.alignRight} ${styles.tokens}`} role="cell">
                  {formatTokens(member.tokens)}
                </span>
                <span className={`${styles.alignRight} ${styles.avg}`} role="cell">
                  {formatTokens(member.avg_tokens_per_session)}
                </span>
              </button>
            );
          })
        ) : (
          Array.from({ length: PLACEHOLDER_ROW_COUNT }).map((_, i) => (
            <div
              className={styles.row}
              key={`placeholder-${i}`}
              data-testid="team-row-skeleton"
              aria-hidden="true"
            >
              <div className={styles.skeletonAvatarCell}>
                <div className={styles.skeletonAvatar} />
                <div className={styles.skeletonCell} />
              </div>
              <div className={styles.skeletonCell} />
              <div className={`${styles.skeletonCell} ${styles.alignRight}`} />
              <div className={`${styles.skeletonCell} ${styles.alignRight}`} />
              <div className={`${styles.skeletonCell} ${styles.alignRight}`} />
            </div>
          ))
        )}
      </div>
      <span aria-live="polite" className={styles.visuallyHidden}>
        {status === "loading"
          ? "Loading project team"
          : status === "error"
            ? "Failed to load project team"
            : `Project team updated for ${rangeLabel}`}
      </span>
      {openMember && (
        <MemberUsagePopup
          programId={programId}
          memberId={openMember.member_id}
          memberName={openMember.member_name}
          role={openMember.role}
          triggerRef={activeTriggerRef}
          onClose={() => setOpenMember(undefined)}
        />
      )}
    </section>
  );
}
