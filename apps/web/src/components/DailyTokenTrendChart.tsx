"use client";

import { useEffect, useRef, useState } from "react";

import { fetchProgramTokenTrend } from "@/lib/programTokenTrendApi.client";
import type { ProgramTokenTrendData } from "@/types/programTokenTrend";

import styles from "./DailyTokenTrendChart.module.css";

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

/** SVG geometry constants, ported verbatim from the mockup's `areaChart()`
 * (DESIGN.md § Chart area) — not derived, not adjustable per-instance. */
const CHART_WIDTH = 1000;
const CHART_HEIGHT = 240;
const PAD_L = 6;
const PAD_R = 6;
const PAD_T = 16;
const PAD_B = 30;
/** Guards `max(vals) * 1.12` against a divide-by-zero on an all-zero series
 * (DESIGN.md § States, Empty row) — the mockup's demo data never hits this
 * branch since `genDaily()` floors every value at `Math.max(0.03, ...)`, but
 * a real all-zero `points[]` (a program with no activity) does. */
const MIN_AXIS_MAX = 1;

const MONTH_ABBREVIATIONS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/**
 * Formats a raw token count for display (D-04, DESIGN.md § Formatting
 * responsibility).
 *
 * **What the mockup's `fmtM` assumed vs what this implements**: the
 * mockup computes `fmtM = n => n >= 1000 ? (n/1000).toFixed(2)+'B' : n.toFixed(1)+'M'`,
 * which assumes its input `n` is *already scaled to millions* (its own demo
 * data, `genDaily()`, produces values in the tens-to-hundreds range meant to
 * be read as "tens to hundreds of millions of tokens"). Fed a raw token
 * count from this story's API (`period_total`/`avg_per_day`/`points[].tokens`,
 * D-02, all raw ints per `program_token_series.tokens: BigInteger`), `fmtM`
 * mislabels small counts by ~6 orders of magnitude (e.g. 1,200 tokens ->
 * "1.20B").
 *
 * This function instead buckets the *raw* count directly, at the same K/1,000
 * and M/1,000,000 thresholds the backend's own `format_number()`
 * (`services/api/app/utils/format.py`) already uses for every other
 * pre-formatted value on this page -- consistent magnitude vocabulary across
 * the page even though this one section computes it client-side. No `"B"`
 * bucket is added: `format_number()` itself defines only K/M
 * (`docs/requirements/api.md#api-conventions`), and a single day's or even a
 * 90-day period's realistic token sum (`program_token_series.tokens` is a
 * per-day `BigInteger`, but real per-day activity is bounded by a handful of
 * developer sessions) does not plausibly reach billions.
 *
 * Worked examples: `1200 -> "1.2K"`, `45000 -> "45.0K"`, `3400000 -> "3.40M"`,
 * `842 -> "842"`.
 */
export function formatTokens(n: number): string {
  const magnitude = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (magnitude >= 1_000_000) {
    return `${sign}${(magnitude / 1_000_000).toFixed(2)}M`;
  }
  if (magnitude >= 1_000) {
    return `${sign}${(magnitude / 1_000).toFixed(1)}K`;
  }
  return `${sign}${Math.round(magnitude)}`;
}

/** Parses an API `points[].date` (`YYYY-MM-DD`) into an x-axis tick label
 * (`"Mon D"`, e.g. `"Jul 15"`), matching the mockup's `dateLabel()` format
 * without porting its offset-from-today math (DESIGN.md: the real component
 * plots API dates, not `genDaily`'s synthetic offsets). Parsed as UTC
 * components to avoid a local-timezone day shift. */
function formatTickLabel(dateStr: string): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  if (!year || !month || !day) {
    return dateStr;
  }
  return `${MONTH_ABBREVIATIONS[month - 1]} ${day}`;
}

/** Minimal point shape `TokenAreaChart` needs -- satisfied by both
 * `ProgramTokenPointData` (PGD-02) and `MemberDailyTokenPointData` (PGD-05's
 * popup, ADR-0009 amendment), whose raw field is named `tokens` in both
 * shapes on purpose (see `@/types/memberUsage`'s module docstring). */
export interface TokenAreaChartPoint {
  date: string;
  tokens: number;
}

/**
 * Inline SVG area chart over `points[]`, geometry ported from the mockup's
 * `areaChart(vals, days, color)` (DESIGN.md § Chart area) — the function's
 * shape is the spec, its input (`genDaily`'s seeded demo data) is not
 * ported.
 *
 * Exported so PGD-05's `MemberUsagePopup` (DESIGN.md § 2.3 Block 2) can reuse
 * this exact geometry at a shorter rendered height, rather than a second
 * chart implementation (`.claude/rules/reusability-baseline.md`).
 */
export function TokenAreaChart({
  points,
  accentColor,
  height = 240,
}: {
  points: TokenAreaChartPoint[];
  accentColor: string;
  /** Rendered SVG height in px. `viewBox` stays fixed at `CHART_HEIGHT`
   * (`preserveAspectRatio="none"` scales it) -- DESIGN.md § 2.3 Block 2 calls
   * for `180px` in the popup vs. the default `240px` on Program Detail. */
  height?: number;
}) {
  const n = points.length;
  const vals = points.map((p) => p.tokens);
  const rawMax = vals.length > 0 ? Math.max(...vals) : 0;
  const axisMax = Math.max(rawMax * 1.12, MIN_AXIS_MAX);

  const xs = (i: number) => PAD_L + (i / (n - 1 || 1)) * (CHART_WIDTH - PAD_L - PAD_R);
  const ys = (v: number) =>
    PAD_T + (1 - v / axisMax) * (CHART_HEIGHT - PAD_T - PAD_B);

  const pts = vals.map((v, i) => [xs(i), ys(v)] as const);
  const line = pts
    .map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
  const area =
    n > 0
      ? `${line} L${xs(n - 1).toFixed(1)} ${CHART_HEIGHT - PAD_B} L${xs(0).toFixed(
          1,
        )} ${CHART_HEIGHT - PAD_B} Z`
      : "";

  const gradientId = `tokg${n}`;
  const tickCount = n === 7 ? 7 : 6;
  const tickIdx: number[] = [];
  for (let t = 0; t < Math.min(tickCount, n); t++) {
    tickIdx.push(Math.round((t / (Math.min(tickCount, n) - 1 || 1)) * (n - 1)));
  }
  const gridY = [0.25, 0.5, 0.75, 1].map(
    (f) => PAD_T + (1 - f) * (CHART_HEIGHT - PAD_T - PAD_B),
  );

  const last = pts[n - 1];

  return (
    <svg
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      style={{ width: "100%", height: `${height}px`, display: "block" }}
      preserveAspectRatio="none"
      role="img"
      aria-label={`Daily token usage trend, ${n} days, total ${formatTokens(
        vals.reduce((a, b) => a + b, 0),
      )} tokens`}
    >
      <defs>
        <linearGradient id={gradientId} x1={0} y1={0} x2={0} y2={1}>
          <stop offset="0%" stopColor={accentColor} stopOpacity={0.24} />
          <stop offset="100%" stopColor={accentColor} stopOpacity={0} />
        </linearGradient>
      </defs>
      {gridY.map((y, i) => (
        <line
          key={`g${i}`}
          x1={PAD_L}
          y1={y}
          x2={CHART_WIDTH - PAD_R}
          y2={y}
          stroke="#eef0f3"
          strokeWidth={1}
        />
      ))}
      {n > 0 && <path d={area} fill={`url(#${gradientId})`} />}
      {n > 0 && (
        <path
          d={line}
          fill="none"
          stroke={accentColor}
          strokeWidth={2.6}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
      {last && (
        <circle
          cx={last[0]}
          cy={last[1]}
          r={4.5}
          fill="#fff"
          stroke={accentColor}
          strokeWidth={2.6}
        />
      )}
      {tickIdx.map((idx, i) => (
        <text
          key={`t${i}`}
          x={xs(idx)}
          y={CHART_HEIGHT - 9}
          textAnchor={i === 0 ? "start" : i === tickIdx.length - 1 ? "end" : "middle"}
          fontSize={13}
          fontFamily="'Plus Jakarta Sans', sans-serif"
          fontWeight={600}
          fill="#9aa2ae"
        >
          {formatTickLabel(points[idx].date)}
        </text>
      ))}
    </svg>
  );
}

/**
 * "Daily token consumption" card (PGD-02-AC-5, DESIGN.md).
 *
 * Self-fetching client component: owns its own `range` state and refetches
 * via `fetchProgramTokenTrend` (T-09) on mount and on every range-toggle
 * click. This differs from sibling Program Detail components
 * (`ProgramSummaryCards`, `ProgramDetailHeader`), which take server-resolved
 * props -- this section is the one part of the page with its own
 * client-driven refresh cadence (AC-5: toggle must refetch within 2s),
 * mirroring `ProgramSwitcher`'s controlled-but-self-contained shape rather
 * than `ProgramDetailView`'s top-level orchestration.
 *
 * `accentColor` is the page's already-resolved program-type colour
 * (DESIGN.md: "the chart must reuse the page's existing type colour, not
 * pick its own") -- passed in by the mounting parent (T-13), not derived
 * here.
 *
 * States (DESIGN.md § States): `loading` keeps card chrome + range buttons
 * mounted (disabled) and skeletons the stat block + chart at the fixed
 * 240px height so switching ranges never reflows the card. `error` keeps
 * chrome + title, replaces only the chart area with an inline retry.
 * `empty` is not a distinct code path -- the API zero-pads every missing
 * day, so an empty program's `points[]` is full-length all-zero, which
 * renders through the ordinary populated path as a flat line (axis-max
 * guarded against divide-by-zero, see `MIN_AXIS_MAX`).
 */
export function DailyTokenTrendChart({
  programId,
  accentColor,
}: {
  programId: string;
  accentColor: string;
}) {
  const [range, setRange] = useState<RangeKey>(DEFAULT_RANGE);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [data, setData] = useState<ProgramTokenTrendData | undefined>(undefined);

  const latestRequestId = useRef(0);

  function load(nextRange: RangeKey) {
    const requestId = ++latestRequestId.current;
    setStatus("loading");
    fetchProgramTokenTrend(programId, nextRange).then((result) => {
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

  return (
    <section className={styles.section}>
      <div className={styles.header}>
        <div>
          <div className={styles.title}>Daily token consumption</div>
          <div className={styles.subtitle}>AI token usage per day · {rangeLabel}</div>
        </div>
        <div className={styles.rightCluster}>
          <div className={styles.statBlock}>
            {status === "ok" && data ? (
              <>
                <div className={styles.statTotal}>{formatTokens(data.period_total)}</div>
                <div className={styles.statAvg}>
                  total · {formatTokens(data.avg_per_day)} / day avg
                </div>
              </>
            ) : (
              <div
                className={styles.statSkeleton}
                data-testid="token-trend-stat-skeleton"
              />
            )}
          </div>
          <div
            className={styles.toggleTrack}
            role="group"
            aria-label="Select date range for daily token consumption"
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
      <div className={styles.chartArea}>
        {status === "error" ? (
          <div className={styles.errorPanel} role="alert">
            <span>Couldn&apos;t load the token trend.</span>
            <button
              type="button"
              className={styles.retryButton}
              onClick={() => load(range)}
            >
              Retry
            </button>
          </div>
        ) : status === "ok" && data ? (
          <TokenAreaChart points={data.points} accentColor={accentColor} />
        ) : (
          <div
            className={styles.chartSkeleton}
            data-testid="token-trend-chart-skeleton"
            aria-hidden="true"
          />
        )}
      </div>
      <span aria-live="polite" className={styles.visuallyHidden}>
        {status === "loading"
          ? "Loading daily token consumption"
          : status === "error"
            ? "Failed to load daily token consumption"
            : `Daily token consumption updated for ${rangeLabel}`}
      </span>
    </section>
  );
}
