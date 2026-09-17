import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { MemberUsagePopup } from "./MemberUsagePopup";
import type { MemberUsageData } from "@/types/memberUsage";

/**
 * PGD-05-AC-9/AC-11/AC-12 component-level coverage (DESIGN.md § Screen 2).
 *
 * D-09 convention (mirrors `ProgramTeamPanel.test.tsx`): native `vitest`
 * mocks only, no MSW.
 */

const fetchMemberUsage = vi.fn();

vi.mock("@/lib/memberUsageApi.client", () => ({
  fetchMemberUsage: (...args: unknown[]) => fetchMemberUsage(...args),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function usageData(overrides: Partial<MemberUsageData> = {}): MemberUsageData {
  return {
    cards: [
      { glyph: "S", value: "22", label: "Sessions", iconBg: "#eef3fb", iconColor: "#2a6fdb" },
      { glyph: "T", value: "4h 12m", label: "Total time", iconBg: "#eef3fb", iconColor: "#2a6fdb" },
      { glyph: "K", value: "4.2M", label: "Total tokens", iconBg: "#eef3fb", iconColor: "#2a6fdb" },
      { glyph: "A", value: "191K", label: "Avg tokens/session", iconBg: "#eef3fb", iconColor: "#2a6fdb" },
    ],
    daily_tokens: {
      points: [{ date: "2026-09-01", value: "4.2M", tokens: 4_200_000 }],
      period_total: "4.2M",
      avg_per_day: "140K",
    },
    commands: {
      total_runs: "22",
      items: [{ command: "/arh-implement", count: 12, barStyle: "width:100%" }],
    },
    ...overrides,
  };
}

function renderPopup(overrides: Partial<Parameters<typeof MemberUsagePopup>[0]> = {}) {
  const triggerRef = createRef<HTMLButtonElement>();
  const onClose = vi.fn();
  const utils = render(
    <MemberUsagePopup
      programId="PROG-100"
      memberId="Devon Rao"
      memberName="Devon Rao"
      role="Developer"
      triggerRef={triggerRef}
      onClose={onClose}
      {...overrides}
    />,
  );
  return { ...utils, onClose, triggerRef };
}

describe("MemberUsagePopup", () => {
  it("opens immediately with loading placeholders, without waiting on the fetch (DESIGN.md § 2.4)", () => {
    fetchMemberUsage.mockReturnValue(new Promise(() => {}));

    renderPopup();

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Devon Rao")).not.toBeNull();
    expect(screen.getAllByTestId("member-usage-card-skeleton")).toHaveLength(4);
    expect(screen.getByTestId("member-usage-chart-skeleton")).not.toBeNull();
    expect(screen.getByTestId("member-usage-chart-stat-skeleton")).not.toBeNull();
    expect(screen.getAllByTestId("member-usage-command-skeleton")).toHaveLength(6);
  });

  it("renders dialog semantics: role, aria-modal, labelledby/describedby (NFR-008)", () => {
    fetchMemberUsage.mockReturnValue(new Promise(() => {}));

    renderPopup();

    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("aria-labelledby")).not.toBeNull();
    expect(dialog.getAttribute("aria-describedby")).not.toBeNull();
  });

  it("initial focus lands on the close button", async () => {
    fetchMemberUsage.mockReturnValue(new Promise(() => {}));

    renderPopup();

    await waitFor(() =>
      expect(document.activeElement?.getAttribute("aria-label")).toBe(
        "Close usage for Devon Rao",
      ),
    );
  });

  it("renders the 4-card row, the daily-tokens chart, and the commands list on success (AF-05 fix)", async () => {
    fetchMemberUsage.mockResolvedValue({ status: "ok", data: usageData() });

    renderPopup();

    await waitFor(() => expect(screen.getAllByTestId("member-usage-card")).toHaveLength(4));
    expect(screen.getByText("/arh-implement")).not.toBeNull();
    expect(screen.getAllByText("22").length).toBeGreaterThan(0);
    // Chart block renders: plots the raw `tokens` series via the shipped
    // `TokenAreaChart` geometry.
    expect(screen.getByText("Daily token consumption")).not.toBeNull();
    const chart = document.querySelector("svg");
    expect(chart).not.toBeNull();
    expect(chart?.getAttribute("aria-label")).toContain("4.20M tokens");
    expect(screen.getAllByText("4.2M").length).toBeGreaterThan(0);
    expect(screen.getByText(/140K \/ day avg/)).not.toBeNull();
  });

  it("renders the empty-commands copy distinct from the denied state (DESIGN.md § 2.3 Block 3)", async () => {
    fetchMemberUsage.mockResolvedValue({
      status: "ok",
      data: usageData({ commands: { total_runs: "0", items: [] } }),
    });

    renderPopup();

    await waitFor(() =>
      expect(screen.getByText("No commands run in this period.")).not.toBeNull(),
    );
    // Cards and commands card scaffolding are still present -- this is not the denied state.
    expect(screen.getAllByTestId("member-usage-card")).toHaveLength(4);
    expect(screen.getByText("Commands")).not.toBeNull();
  });

  it("AC-12: denied state renders no cards grid, no commands card, and no placeholders", async () => {
    fetchMemberUsage.mockResolvedValue({ status: "denied" });

    renderPopup();

    const dialog = await screen.findByRole("dialog");
    await waitFor(() =>
      expect(
        within(dialog).getByRole("status").textContent,
      ).toContain("You don't have access to this member's usage"),
    );

    expect(screen.queryAllByTestId("member-usage-card")).toHaveLength(0);
    expect(screen.queryAllByTestId("member-usage-card-skeleton")).toHaveLength(0);
    expect(screen.queryAllByTestId("member-usage-command-skeleton")).toHaveLength(0);
    expect(screen.queryByText("Commands")).toBeNull();
    // No chart shell either -- an empty/zeroed chart would falsely assert
    // "this member's usage is zero" (DESIGN.md § 2.5 hard rule).
    expect(screen.queryByText("Daily token consumption")).toBeNull();
    expect(document.querySelector("svg")).toBeNull();
    expect(screen.queryAllByTestId("member-usage-chart-skeleton")).toHaveLength(0);
    expect(screen.queryAllByTestId("member-usage-chart-stat-skeleton")).toHaveLength(0);
    expect(
      screen.getByText(
        "Individual usage is visible to the member themselves and to CIO-level roles.",
      ),
    ).not.toBeNull();
    // No retry button on denied -- denial isn't transient (AC-11).
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    // No range chips -- no data for a range to scope.
    expect(screen.queryByRole("group", { name: "Select date range for member usage" })).toBeNull();
  });

  it("AC-11: error state is structurally distinct from denied -- different glyph/copy and a retry button", async () => {
    fetchMemberUsage.mockResolvedValue({ status: "error" });

    renderPopup();

    const retryButton = await screen.findByRole("button", { name: "Retry" });
    expect(retryButton).not.toBeNull();
    expect(screen.getByText("Couldn't load this member's usage")).not.toBeNull();
    expect(screen.queryByText("You don't have access to this member's usage")).toBeNull();
    // Range chips remain enabled on error -- changing range is a legitimate retry path.
    expect(
      screen.getByRole("group", { name: "Select date range for member usage" }),
    ).not.toBeNull();
  });

  it("retry re-issues the request at the current range", async () => {
    fetchMemberUsage.mockResolvedValueOnce({ status: "error" });

    renderPopup();

    const retryButton = await screen.findByRole("button", { name: "Retry" });

    fetchMemberUsage.mockResolvedValueOnce({ status: "ok", data: usageData() });
    fireEvent.click(retryButton);

    await waitFor(() => expect(screen.getAllByTestId("member-usage-card")).toHaveLength(4));
    expect(fetchMemberUsage).toHaveBeenLastCalledWith("PROG-100", "Devon Rao", "30d");
  });

  it("Esc dismisses the popup", async () => {
    fetchMemberUsage.mockReturnValue(new Promise(() => {}));

    const { onClose } = renderPopup();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("overlay click dismisses; panel click does not propagate to the overlay", async () => {
    fetchMemberUsage.mockReturnValue(new Promise(() => {}));

    const { onClose } = renderPopup();

    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("member-usage-overlay"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("close button dismisses with an accessible name naming the member", async () => {
    fetchMemberUsage.mockReturnValue(new Promise(() => {}));

    const { onClose } = renderPopup();

    fireEvent.click(screen.getByRole("button", { name: "Close usage for Devon Rao" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("range switch re-fetches with the new range", async () => {
    fetchMemberUsage.mockResolvedValue({ status: "ok", data: usageData() });

    renderPopup();

    await waitFor(() =>
      expect(fetchMemberUsage).toHaveBeenCalledWith("PROG-100", "Devon Rao", "30d"),
    );

    const btn7d = screen.getByRole("button", { name: "7D" });
    fireEvent.click(btn7d);

    await waitFor(() =>
      expect(fetchMemberUsage).toHaveBeenCalledWith("PROG-100", "Devon Rao", "7d"),
    );
  });
});
