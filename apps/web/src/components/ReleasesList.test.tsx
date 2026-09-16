import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ReleasesList } from "./ReleasesList";
import type { ProgramReleasesData, ProgramReleasesResult } from "@/types/programReleases";

/**
 * PGD-03-TC-12/13/14 (manual/e2e, `automatable: false` per test-cases/PGD-03.json)
 * + D-02 tag-color/tag-bg hoisting regression guard.
 *
 * These are the automatable component-level ANALOGUE of TC-12/13/14 per
 * PLAN.md § 7 -- not a substitute for the e2e visual/scroll assertion, which
 * stays manual until Playwright is wired (test_e2e deferred per
 * project-commands.yaml).
 *
 * D-09 convention (mirrors DailyTokenTrendChart.test.tsx): native `vitest`
 * mocks only, no MSW. `@/lib/programDetailApi.client` is mocked via its
 * `@/*` alias.
 */

const fetchProgramReleases = vi.fn();

vi.mock("@/lib/programDetailApi.client", () => ({
  fetchProgramReleases: (...args: unknown[]) => fetchProgramReleases(...args),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function okResult(
  items: ProgramReleasesData["items"],
  relTotal: string,
  tagColor = "#2a6fdb",
  tagBg = "#e8f0fe",
): ProgramReleasesResult {
  return {
    status: "ok",
    data: { items, relTotal, tagColor, tagBg },
  };
}

function row(overrides: Partial<ProgramReleasesData["items"][number]> = {}) {
  return {
    ver: "v2.4.0",
    label: "Feature release",
    dot: "#1f8a5b",
    date: "Jul 15",
    stories: "12",
    prs: "8",
    ...overrides,
  };
}

describe("ReleasesList", () => {
  it("TC-14 analogue: renders exactly 6 placeholder rows while loading", () => {
    fetchProgramReleases.mockReturnValue(new Promise(() => {})); // never resolves

    render(<ReleasesList programId="PROG-100" />);

    const skeletons = screen.getAllByTestId("releases-row-skeleton");
    expect(skeletons).toHaveLength(6);
  });

  it("replaces placeholders with real rows once the API responds", async () => {
    fetchProgramReleases.mockResolvedValue(okResult([row()], "1"));

    render(<ReleasesList programId="PROG-100" />);

    expect(screen.getAllByTestId("releases-row-skeleton")).toHaveLength(6);

    await waitFor(() =>
      expect(screen.queryAllByTestId("releases-row-skeleton")).toHaveLength(0),
    );
    expect(screen.getByText("v2.4.0")).not.toBeNull();
  });

  it("renders all 6 row fields correctly", async () => {
    fetchProgramReleases.mockResolvedValue(
      okResult(
        [
          row({
            ver: "v3.1.2",
            label: "Patch release",
            dot: "#2a6fdb",
            date: "Aug 02",
            stories: "5",
            prs: "3",
          }),
        ],
        "1",
      ),
    );

    render(<ReleasesList programId="PROG-100" />);

    await waitFor(() => expect(screen.getByText("v3.1.2")).not.toBeNull());

    expect(screen.getByText("Patch release")).not.toBeNull();
    expect(screen.getByText("Aug 02")).not.toBeNull();
    expect(screen.getByText("5")).not.toBeNull();
    expect(screen.getByText("3")).not.toBeNull();

    // Stat value (relTotal) also rendered.
    expect(screen.getByText("1")).not.toBeNull();
    expect(screen.getByText("releases shipped")).not.toBeNull();
  });

  it("D-02 regression guard: tagColor/tagBg on the version tag come from the response's TOP-LEVEL fields, not per-row fields, and apply to every row identically", async () => {
    fetchProgramReleases.mockResolvedValue(
      okResult(
        [
          row({ ver: "v1.0.0", label: "Feature release" }),
          row({ ver: "v1.0.1", label: "Hotfix" }),
          row({ ver: "v1.0.2", label: "Patch release" }),
        ],
        "3",
        "#d1495b",
        "#fbe9ec",
      ),
    );

    render(<ReleasesList programId="PROG-100" />);

    await waitFor(() => expect(screen.getByText("v1.0.0")).not.toBeNull());

    const tagV100 = screen.getByText("v1.0.0");
    const tagV101 = screen.getByText("v1.0.1");
    const tagV102 = screen.getByText("v1.0.2");

    // Every row's tag carries the SAME top-level tagColor/tagBg -- not a
    // per-row value (there is no such field on ProgramReleaseItemData at
    // all; this proves the binding source, not merely the visual outcome).
    for (const tag of [tagV100, tagV101, tagV102]) {
      expect(tag.style.color).toBe("rgb(209, 73, 91)"); // #d1495b
      expect(tag.style.background).toBe("rgb(251, 233, 236)"); // #fbe9ec
    }
  });

  it("empty state renders when there are no releases in range", async () => {
    fetchProgramReleases.mockResolvedValue(okResult([], "0"));

    render(<ReleasesList programId="PROG-100" />);

    await waitFor(() =>
      expect(screen.getByText("No releases in this range.")).not.toBeNull(),
    );
    expect(screen.getByText("0")).not.toBeNull();
    expect(screen.queryAllByTestId("releases-row-skeleton")).toHaveLength(0);
  });

  it("range-switcher click triggers its own refetch with the new range, independent of any sibling chart control", async () => {
    // A stubbed sibling control (standing in for PGD-02's DailyTokenTrendChart
    // switcher) that must remain untouched by this component's switcher.
    const siblingChartSwitch = vi.fn();

    fetchProgramReleases.mockResolvedValue(okResult([row()], "1"));

    render(
      <>
        <button onClick={siblingChartSwitch}>Sibling chart 7D</button>
        <ReleasesList programId="PROG-100" />
      </>,
    );

    await waitFor(() =>
      expect(fetchProgramReleases).toHaveBeenCalledWith("PROG-100", "30d", 0, 20),
    );

    fetchProgramReleases.mockResolvedValue(
      okResult([row({ ver: "v9.9.9" })], "1"),
    );

    const btn90d = screen.getByRole("button", { name: "90D" });
    fireEvent.click(btn90d);

    await waitFor(() =>
      expect(fetchProgramReleases).toHaveBeenCalledWith("PROG-100", "90d", 0, 20),
    );
    await waitFor(() => expect(screen.getByText("v9.9.9")).not.toBeNull());

    // The sibling chart control was never invoked by this component's switch.
    expect(siblingChartSwitch).not.toHaveBeenCalled();
    // Only ReleasesList's own fetch fired -- twice (initial mount + one range change).
    expect(fetchProgramReleases).toHaveBeenCalledTimes(2);
  });

  it("error state (network/timeout) renders a retry affordance and no rows", async () => {
    fetchProgramReleases.mockResolvedValue({ status: "error" });

    render(<ReleasesList programId="PROG-100" />);

    const retryButton = await screen.findByRole("button", { name: "Retry" });
    expect(retryButton).not.toBeNull();
    expect(screen.queryByText("v2.4.0")).toBeNull();
  });

  it("not_found result renders the same error/retry state as a generic error", async () => {
    fetchProgramReleases.mockResolvedValue({ status: "not_found" });

    render(<ReleasesList programId="PROG-100" />);

    const retryButton = await screen.findByRole("button", { name: "Retry" });
    expect(retryButton).not.toBeNull();
  });

  it("unauthorized result renders the same error/retry state as a generic error", async () => {
    fetchProgramReleases.mockResolvedValue({ status: "unauthorized" });

    render(<ReleasesList programId="PROG-100" />);

    const retryButton = await screen.findByRole("button", { name: "Retry" });
    expect(retryButton).not.toBeNull();
  });

  it("retry button re-invokes the fetch for the current range and recovers to the ok state", async () => {
    fetchProgramReleases.mockResolvedValue({ status: "error" });

    render(<ReleasesList programId="PROG-100" />);

    const retryButton = await screen.findByRole("button", { name: "Retry" });

    fetchProgramReleases.mockResolvedValue(okResult([row()], "1"));
    fireEvent.click(retryButton);

    await waitFor(() => expect(screen.getByText("v2.4.0")).not.toBeNull());
    expect(fetchProgramReleases).toHaveBeenLastCalledWith("PROG-100", "30d", 0, 20);
  });

  it("the range switcher is keyboard-operable: real buttons with aria-pressed reflecting the active range", async () => {
    fetchProgramReleases.mockResolvedValue(okResult([row()], "1"));

    render(<ReleasesList programId="PROG-100" />);

    await waitFor(() =>
      expect(fetchProgramReleases).toHaveBeenCalledWith("PROG-100", "30d", 0, 20),
    );

    const group = screen.getByRole("group", {
      name: "Select date range for releases via Harness",
    });
    const btn7d = within(group).getByRole("button", { name: "7D" });
    const btn30d = within(group).getByRole("button", { name: "30D" });
    const btn90d = within(group).getByRole("button", { name: "90D" });

    // Default range (30d) is active.
    expect(btn30d.getAttribute("aria-pressed")).toBe("true");
    expect(btn7d.getAttribute("aria-pressed")).toBe("false");
    expect(btn90d.getAttribute("aria-pressed")).toBe("false");

    fetchProgramReleases.mockResolvedValue(okResult([row()], "1"));
    fireEvent.click(btn7d);

    await waitFor(() => expect(btn7d.getAttribute("aria-pressed")).toBe("true"));
    expect(btn30d.getAttribute("aria-pressed")).toBe("false");
  });
});
