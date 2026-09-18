/** SVG geometry constants, ported verbatim from the mockup's `spark()`
 * (DESIGN.md § Chart — `spark()`) — not derived, not adjustable per-instance. */
const VIEW_WIDTH = 240;
const VIEW_HEIGHT = 56;
const PAD = 4;

/** One point of `sparkline.points[]` (OVW-04-FR-1) — raw ints, the frontend
 * owns the chart entirely. */
export interface ProgramSparklinePoint {
  month: string;
  tokens: number;
}

/**
 * Inline SVG mini-chart for a program board card's monthly token
 * consumption panel, geometry ported verbatim from the mockup's
 * `spark()` (DESIGN.md § Chart — `spark()`), the way
 * `DailyTokenTrendChart.tsx`'s `TokenAreaChart` ports `areaChart()`.
 *
 * `typeColor` is the page's already-resolved program-type colour
 * (`programStyle.ts`) — the stroke, area fill, and end dot are all tinted
 * with it, never a fixed chart colour (DESIGN.md § Chart).
 *
 * Divide-by-zero guards the mockup's own demo data never reaches (its
 * `monthly` arrays are all 12-point, non-zero) but real data does
 * (DESIGN.md § Chart, same class of guard `TokenAreaChart`'s `MIN_AXIS_MAX`
 * documents):
 * - `n === 1` renders a single centered dot, no line.
 * - `n === 0` renders an empty 56px-tall panel body — no axes, no text.
 *
 * Decorative: `role="img"` with `aria-hidden="true"` (DESIGN.md § Keyboard
 * and assistive tech) — the MoM chip already states the trend numerically.
 */
export function ProgramSparkline({
  points,
  typeColor,
}: {
  points: ProgramSparklinePoint[];
  typeColor: string;
}) {
  const n = points.length;

  if (n === 0) {
    return (
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        style={{ width: "100%", height: `${VIEW_HEIGHT}px`, display: "block" }}
        preserveAspectRatio="none"
        role="img"
        aria-hidden="true"
      />
    );
  }

  const gradientId = `spark-${n}-${typeColor.replace("#", "")}`;

  if (n === 1) {
    const cx = PAD;
    const cy = VIEW_HEIGHT / 2;
    return (
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        style={{ width: "100%", height: `${VIEW_HEIGHT}px`, display: "block" }}
        preserveAspectRatio="none"
        role="img"
        aria-hidden="true"
      >
        <circle cx={cx} cy={cy} r={4} fill="#fff" stroke={typeColor} strokeWidth={2.4} />
      </svg>
    );
  }

  const vals = points.map((p) => p.tokens);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const rng = max - min || 1;

  const xs = (i: number) => PAD + (i / (n - 1)) * (VIEW_WIDTH - PAD * 2);
  const ys = (v: number) =>
    PAD + (1 - (v - min) / rng) * (VIEW_HEIGHT - PAD * 2 - 6);

  const pts = vals.map((v, i) => [xs(i), ys(v)] as const);
  const line = pts
    .map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
  const area = `${line} L${xs(n - 1).toFixed(1)} ${VIEW_HEIGHT - PAD} L${xs(0).toFixed(
    1,
  )} ${VIEW_HEIGHT - PAD} Z`;

  const last = pts[n - 1];

  return (
    <svg
      viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      style={{ width: "100%", height: `${VIEW_HEIGHT}px`, display: "block" }}
      preserveAspectRatio="none"
      role="img"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradientId} x1={0} y1={0} x2={0} y2={1}>
          <stop offset="0%" stopColor={typeColor} stopOpacity={0.22} />
          <stop offset="100%" stopColor={typeColor} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path
        d={line}
        fill="none"
        stroke={typeColor}
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={last[0]}
        cy={last[1]}
        r={4}
        fill="#fff"
        stroke={typeColor}
        strokeWidth={2.4}
      />
    </svg>
  );
}
