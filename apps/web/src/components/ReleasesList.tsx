"use client";

import { useEffect, useRef, useState } from "react";

import { fetchProgramReleases } from "@/lib/programDetailApi.client";
import type { ProgramReleasesData } from "@/types/programReleases";

import styles from "./ReleasesList.module.css";

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

/** DESIGN.md § Row list: `hint-placeholder-count="6"` — six skeleton rows
 * for the loading state. */
const PLACEHOLDER_ROW_COUNT = 6;

/** PLAN.md § 6 / PRD Scope: render only the first page, endpoint defaults. */
const DEFAULT_OFFSET = 0;
const DEFAULT_LIMIT = 20;

/**
 * Releases panel (Program Detail, PGD-03 T-13, DESIGN.md § Releases panel).
 *
 * Self-fetching client component: owns its own `range` state and its own
 * fetch, independent of PGD-02's `DailyTokenTrendChart` switcher (DESIGN.md:
 * "The switcher is independent of PGD-02's chart switcher — changing the
 * range here refetches only this panel"). Mirrors `DailyTokenTrendChart`'s
 * range-state / fetch-guard idiom.
 *
 * States (DESIGN.md § Row list / § Not specified by the mockup): `loading`
 * renders `PLACEHOLDER_ROW_COUNT` skeleton rows; `error` replaces the row
 * list with an inline retry; `empty` (0 releases in range) is a copy-only
 * state the mockup doesn't specify — brief, plain copy per PLAN.md.
 *
 * Values (`ver`, `label`, `date`, `stories`, `prs`, `relTotal`) arrive
 * pre-formatted from the API (DESIGN.md § Pre-formatted values) — this
 * component formats nothing.
 */
export function ReleasesList({ programId }: { programId: string }) {
  const [range, setRange] = useState<RangeKey>(DEFAULT_RANGE);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [data, setData] = useState<ProgramReleasesData | undefined>(undefined);

  const latestRequestId = useRef(0);

  function load(nextRange: RangeKey) {
    const requestId = ++latestRequestId.current;
    setStatus("loading");
    fetchProgramReleases(programId, nextRange, DEFAULT_OFFSET, DEFAULT_LIMIT).then(
      (result) => {
        if (requestId !== latestRequestId.current) {
          return;
        }
        if (result.status === "ok") {
          setData(result.data);
          setStatus("ok");
        } else {
          setStatus("error");
        }
      },
    );
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
          <div className={styles.title}>Releases via Harness</div>
          <div className={styles.subtitle}>
            Releases shipped with Harness · {rangeLabel}
          </div>
        </div>
        <div className={styles.rightCluster}>
          <div className={styles.statBlock}>
            {status === "ok" && data ? (
              <>
                <div className={styles.statTotal}>{data.relTotal}</div>
                <div className={styles.statCaption}>releases shipped</div>
              </>
            ) : (
              <div
                className={styles.statSkeleton}
                data-testid="releases-stat-skeleton"
              />
            )}
          </div>
          <div
            className={styles.toggleTrack}
            role="group"
            aria-label="Select date range for releases via Harness"
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
      </div>
      <div className={styles.columnHeaders}>
        <span>Version</span>
        <span>Release</span>
        <span>Date</span>
        <span className={styles.alignRight}>Stories</span>
        <span className={styles.alignRight}>PRs merged</span>
      </div>
      <div className={styles.scrollContainer}>
        {status === "error" ? (
          <div className={styles.errorPanel} role="alert">
            <span>Couldn&apos;t load releases.</span>
            <button
              type="button"
              className={styles.retryButton}
              onClick={() => load(range)}
            >
              Retry
            </button>
          </div>
        ) : isEmpty ? (
          <div className={styles.emptyPanel}>No releases in this range.</div>
        ) : status === "ok" && data ? (
          data.items.map((r, i) => (
            <div className={styles.row} key={`${r.ver}-${i}`}>
              <code
                className={styles.versionTag}
                style={{ color: data.tagColor, background: data.tagBg }}
              >
                {r.ver}
              </code>
              <div className={styles.releaseCell}>
                <span
                  className={styles.dot}
                  style={{ background: r.dot }}
                  aria-hidden="true"
                />
                <span className={styles.releaseLabel}>{r.label}</span>
              </div>
              <div className={styles.date}>{r.date}</div>
              <div className={styles.alignRight}>{r.stories}</div>
              <div className={`${styles.alignRight} ${styles.prs}`}>{r.prs}</div>
            </div>
          ))
        ) : (
          Array.from({ length: PLACEHOLDER_ROW_COUNT }).map((_, i) => (
            <div
              className={styles.row}
              key={`placeholder-${i}`}
              data-testid="releases-row-skeleton"
              aria-hidden="true"
            >
              <div className={styles.skeletonCell} />
              <div className={styles.skeletonCell} />
              <div className={styles.skeletonCell} />
              <div className={`${styles.skeletonCell} ${styles.alignRight}`} />
              <div className={`${styles.skeletonCell} ${styles.alignRight}`} />
            </div>
          ))
        )}
      </div>
      <span aria-live="polite" className={styles.visuallyHidden}>
        {status === "loading"
          ? "Loading releases"
          : status === "error"
            ? "Failed to load releases"
            : `Releases updated for ${rangeLabel}`}
      </span>
    </section>
  );
}
