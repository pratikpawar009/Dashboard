import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { DailyTokenTrendChart, formatTokens } from "./DailyTokenTrendChart";
import type { ProgramTokenTrendResult } from "@/types/programTokenTrend";

/**
 * PGD-02-TC-05..TC-09 (rendering-side assertions) + D-04 formatting
 * regression guard.
 *
 * D-09 convention (mirrors ProgramDetailView.test.tsx): native `vitest`
 * mocks only, no MSW. `@/lib/programTokenTrendApi.client` is mocked via its
 * `@/*` alias.
 */

const fetchProgramTokenTrend = vi.fn();

vi.mock("@/lib/programTokenTrendApi.client", () => ({
  fetchProgramTokenTrend: (...args: unknown[]) => fetchProgramTokenTrend(...args),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function okResult(
  points: { date: string; tokens: number }[],
  periodTotal: number,
  avgPerDay: number,
): ProgramTokenTrendResult {
  return {
    status: "ok",
    data: { points, period_total: periodTotal, avg_per_day: avgPerDay },
  };
}

function daysSeries(n: number, tokensEach: number) {
  return Array.from({ length: n }).map((_, i) => ({
    date: `2026-08-${String(i + 1).padStart(2, "0")}`,
    tokens: tokensEach,
  }));
}

describe("formatTokens (D-04 regression guard)", () => {
  // These assert the component's OWN threshold ladder (D-04:
  // < 1,000 bare; >= 1,000 "{(n/1000).toFixed(1)}K"; >= 1,000,000
  // "{(n/1_000_000).toFixed(2)}M"), which is a deliberate divergence from
  // the mockup's `fmtM` (assumes input pre-scaled to millions). If a future
  // change restores `fmtM` verbatim, `1200` would render "1.20B" instead of
  // "1.2K" and every assertion below fails.
  it.each([
    [1200, "1.2K"],
    [45000, "45.0K"],
    [3400000, "3.40M"],
    [842, "842"],
  ])("formatTokens(%i) === %s", (input, expected) => {
    expect(formatTokens(input)).toBe(expected);
  });

  it("never produces a 'B' suffix for realistic raw token magnitudes (the fmtM regression shape)", () => {
    // fmtM(1200) would be "1.20B" (1200/1000, 2dp, +"B"). Assert the actual
    // output contains no "B" suffix at all for this and neighbouring values.
    for (const raw of [1200, 45000, 3400000, 842, 999, 1000, 999999, 1000000]) {
      expect(formatTokens(raw)).not.toMatch(/B$/);
    }
  });
});

describe("DailyTokenTrendChart", () => {
  it("TC-06: an all-zero series renders the full-length series, not an empty/absent chart", async () => {
    fetchProgramTokenTrend.mockResolvedValue(
      okResult(daysSeries(30, 0), 0, 0),
    );

    render(<DailyTokenTrendChart programId="PROG-200" accentColor="#123456" />);

    await waitFor(() =>
      expect(screen.getByRole("img")).not.toBeNull(),
    );

    const chart = screen.getByRole("img");
    // Accessible name carries the day count and total -- proves the full
    // 30-point series reached the SVG, not a collapsed/absent render.
    expect(chart.getAttribute("aria-label")).toBe(
      "Daily token usage trend, 30 days, total 0 tokens",
    );
    // Zero-value totals render via the ordinary populated path.
    expect(screen.getByText("0")).not.toBeNull();
  });

  it("TC-05: a partially zero-padded series still renders every point (mixed zero/non-zero)", async () => {
    const points = [
      { date: "2026-08-01", tokens: 0 },
      { date: "2026-08-02", tokens: 0 },
      { date: "2026-08-03", tokens: 50 },
      { date: "2026-08-04", tokens: 0 },
      { date: "2026-08-05", tokens: 0 },
      { date: "2026-08-06", tokens: 0 },
      { date: "2026-08-07", tokens: 50 },
    ];
    fetchProgramTokenTrend.mockResolvedValue(okResult(points, 100, 14));

    render(<DailyTokenTrendChart programId="PROG-100" accentColor="#123456" />);

    await waitFor(() => expect(screen.getByRole("img")).not.toBeNull());

    const chart = screen.getByRole("img");
    expect(chart.getAttribute("aria-label")).toBe(
      "Daily token usage trend, 7 days, total 100 tokens",
    );
  });

  it("D-04: renders formatted period_total and avg_per_day using the component's own thresholds", async () => {
    fetchProgramTokenTrend.mockResolvedValue(
      okResult(daysSeries(30, 40000), 1200000, 40000),
    );

    render(<DailyTokenTrendChart programId="PROG-100" accentColor="#123456" />);

    await waitFor(() =>
      expect(screen.getByText("1.20M")).not.toBeNull(),
    );
    expect(screen.getByText(/40\.0K \/ day avg/)).not.toBeNull();
  });

  it("AC-5: range toggle buttons are real buttons with aria-pressed reflecting the active range, and clicking refetches", async () => {
    fetchProgramTokenTrend.mockResolvedValue(
      okResult(daysSeries(30, 100), 3000, 100),
    );

    render(<DailyTokenTrendChart programId="PROG-100" accentColor="#123456" />);

    await waitFor(() =>
      expect(fetchProgramTokenTrend).toHaveBeenCalledWith("PROG-100", "30d"),
    );

    const btn7d = screen.getByRole("button", { name: "7D" });
    const btn30d = screen.getByRole("button", { name: "30D" });
    const btn90d = screen.getByRole("button", { name: "90D" });

    // Default range (30d) is active.
    expect(btn30d.getAttribute("aria-pressed")).toBe("true");
    expect(btn7d.getAttribute("aria-pressed")).toBe("false");
    expect(btn90d.getAttribute("aria-pressed")).toBe("false");

    fetchProgramTokenTrend.mockResolvedValue(
      okResult(daysSeries(7, 200), 1400, 200),
    );

    fireEvent.click(btn7d);

    await waitFor(() =>
      expect(fetchProgramTokenTrend).toHaveBeenCalledWith("PROG-100", "7d"),
    );
    await waitFor(() => expect(btn7d.getAttribute("aria-pressed")).toBe("true"));
    expect(btn30d.getAttribute("aria-pressed")).toBe("false");

    fetchProgramTokenTrend.mockResolvedValue(
      okResult(daysSeries(90, 10), 900, 10),
    );

    fireEvent.click(btn90d);

    await waitFor(() =>
      expect(fetchProgramTokenTrend).toHaveBeenCalledWith("PROG-100", "90d"),
    );
    await waitFor(() => expect(btn90d.getAttribute("aria-pressed")).toBe("true"));
  });

  it("AC-5/NFR-008: the toggle group and chart each expose an accessible name", async () => {
    fetchProgramTokenTrend.mockResolvedValue(
      okResult(daysSeries(30, 10), 300, 10),
    );

    render(<DailyTokenTrendChart programId="PROG-100" accentColor="#123456" />);

    // Toggle group is queryable by its accessible group role/name.
    expect(
      screen.getByRole("group", {
        name: "Select date range for daily token consumption",
      }),
    ).not.toBeNull();

    await waitFor(() =>
      expect(
        screen.getByRole("img", { name: /Daily token usage trend/ }),
      ).not.toBeNull(),
    );
  });

  it("TC-09-adjacent: renders raw period_total (100) and its D-03 avg_per_day (14) verbatim via formatTokens", async () => {
    fetchProgramTokenTrend.mockResolvedValue(
      okResult(daysSeries(7, 0), 100, 14),
    );

    render(<DailyTokenTrendChart programId="PROG-100" accentColor="#123456" />);

    await waitFor(() => expect(screen.getByText("100")).not.toBeNull());
    expect(screen.getByText(/14 \/ day avg/)).not.toBeNull();
  });

  it("error state renders a retry affordance and does not render the chart", async () => {
    fetchProgramTokenTrend.mockResolvedValue({ status: "error" });

    render(<DailyTokenTrendChart programId="PROG-100" accentColor="#123456" />);

    const retryButton = await screen.findByRole("button", { name: "Retry" });
    expect(retryButton).not.toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });
});
