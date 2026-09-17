import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ProgramTeamPanel } from "./ProgramTeamPanel";
import type {
  ProgramTeamData,
  ProgramTeamResult,
  ProgramTeamRowData,
} from "@/types/programTeam";

/**
 * PGD-05-AC-1/AC-6 component-level coverage (DESIGN.md § Screen 1).
 *
 * D-09 convention (mirrors `ReleasesList.test.tsx` / `DailyTokenTrendChart.test.tsx`):
 * native `vitest` mocks only, no MSW. `@/lib/programTeamApi.client` is
 * mocked via its `@/*` alias.
 */

const fetchProgramTeam = vi.fn();
const fetchMemberUsage = vi.fn();

vi.mock("@/lib/programTeamApi.client", () => ({
  fetchProgramTeam: (...args: unknown[]) => fetchProgramTeam(...args),
}));

vi.mock("@/lib/memberUsageApi.client", () => ({
  fetchMemberUsage: (...args: unknown[]) => fetchMemberUsage(...args),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function okResult(items: ProgramTeamData["items"]): ProgramTeamResult {
  return { status: "ok", data: { items } };
}

function member(overrides: Partial<ProgramTeamRowData> = {}): ProgramTeamRowData {
  return {
    member_id: "user-riley-fox",
    member_name: "Riley Fox",
    role: "Developer",
    sessions: 22,
    tokens: 4_200_000,
    avg_tokens_per_session: 191_000,
    ...overrides,
  };
}

describe("ProgramTeamPanel", () => {
  it("TC analogue: renders exactly 7 placeholder rows while loading", () => {
    fetchProgramTeam.mockReturnValue(new Promise(() => {})); // never resolves

    render(<ProgramTeamPanel programId="PROG-100" />);

    expect(screen.getAllByTestId("team-row-skeleton")).toHaveLength(7);
  });

  it("replaces placeholders with real rows once the API responds", async () => {
    fetchProgramTeam.mockResolvedValue(okResult([member()]));

    render(<ProgramTeamPanel programId="PROG-100" />);

    expect(screen.getAllByTestId("team-row-skeleton")).toHaveLength(7);

    await waitFor(() =>
      expect(screen.queryAllByTestId("team-row-skeleton")).toHaveLength(0),
    );
    expect(screen.getByText("Riley Fox")).not.toBeNull();
  });

  it("renders every field per row, with sessions/tokens/avg formatted client-side from raw ints", async () => {
    fetchProgramTeam.mockResolvedValue(
      okResult([
        member({
          member_name: "Devon Rao",
          role: "Architect",
          sessions: 18,
          tokens: 3_400_000,
          avg_tokens_per_session: 188_888,
        }),
      ]),
    );

    render(<ProgramTeamPanel programId="PROG-100" />);

    await waitFor(() => expect(screen.getByText("Devon Rao")).not.toBeNull());

    expect(screen.getByText("Architect")).not.toBeNull();
    expect(screen.getByText("18")).not.toBeNull();
    // formatTokens: 3_400_000 -> "3.40M"
    expect(screen.getByText("3.40M")).not.toBeNull();
    // formatTokens: 188_888 -> "188.9K"
    expect(screen.getByText("188.9K")).not.toBeNull();

    // Avatar initials derived client-side (DR) -- not part of the API row.
    expect(screen.getByText("DR")).not.toBeNull();
  });

  it("derives the avatar background from role via the QA Engineer token (docs/design/tokens.md)", async () => {
    fetchProgramTeam.mockResolvedValue(
      okResult([member({ member_name: "Sam Ito", role: "QA Engineer" })]),
    );

    render(<ProgramTeamPanel programId="PROG-100" />);

    await waitFor(() => expect(screen.getByText("Sam Ito")).not.toBeNull());

    const avatar = screen.getByText("SI");
    expect(avatar.style.background).toBe("rgb(209, 73, 91)"); // #d1495b
  });

  it("empty state renders the documented literal copy, not an error", async () => {
    fetchProgramTeam.mockResolvedValue(okResult([]));

    render(<ProgramTeamPanel programId="PROG-100" />);

    await waitFor(() =>
      expect(screen.getByText("No active members in this range.")).not.toBeNull(),
    );
    expect(screen.queryAllByTestId("team-row-skeleton")).toHaveLength(0);
  });

  it("header carries no total/aggregate value, unlike PGD-04's commands panel", async () => {
    fetchProgramTeam.mockResolvedValue(okResult([member()]));

    render(<ProgramTeamPanel programId="PROG-100" />);

    await waitFor(() => expect(screen.getByText("Riley Fox")).not.toBeNull());

    expect(screen.getByText("Project team")).not.toBeNull();
    expect(screen.getByText("Members & contribution · last 30 days")).not.toBeNull();
  });

  it("range-switcher click triggers its own refetch with the new range, independent of any sibling panel", async () => {
    const siblingPanelSwitch = vi.fn();

    fetchProgramTeam.mockResolvedValue(okResult([member()]));

    render(
      <>
        <button onClick={siblingPanelSwitch}>Sibling panel 7D</button>
        <ProgramTeamPanel programId="PROG-100" />
      </>,
    );

    await waitFor(() =>
      expect(fetchProgramTeam).toHaveBeenCalledWith("PROG-100", "30d"),
    );

    fetchProgramTeam.mockResolvedValue(
      okResult([member({ member_name: "Maya Chen" })]),
    );

    const btn7d = screen.getByRole("button", { name: "7D" });
    fireEvent.click(btn7d);

    await waitFor(() =>
      expect(fetchProgramTeam).toHaveBeenCalledWith("PROG-100", "7d"),
    );
    await waitFor(() => expect(screen.getByText("Maya Chen")).not.toBeNull());

    expect(siblingPanelSwitch).not.toHaveBeenCalled();
    expect(fetchProgramTeam).toHaveBeenCalledTimes(2);
  });

  it("error state (network/timeout) renders a retry affordance and no rows", async () => {
    fetchProgramTeam.mockResolvedValue({ status: "error" });

    render(<ProgramTeamPanel programId="PROG-100" />);

    const retryButton = await screen.findByRole("button", { name: "Retry" });
    expect(retryButton).not.toBeNull();
    expect(screen.queryByText("Riley Fox")).toBeNull();
  });

  it("unauthorized result renders the same error/retry state as a generic error", async () => {
    fetchProgramTeam.mockResolvedValue({ status: "unauthorized" });

    render(<ProgramTeamPanel programId="PROG-100" />);

    const retryButton = await screen.findByRole("button", { name: "Retry" });
    expect(retryButton).not.toBeNull();
  });

  it("retry button re-invokes the fetch for the current range and recovers to the ok state", async () => {
    fetchProgramTeam.mockResolvedValue({ status: "error" });

    render(<ProgramTeamPanel programId="PROG-100" />);

    const retryButton = await screen.findByRole("button", { name: "Retry" });

    fetchProgramTeam.mockResolvedValue(okResult([member()]));
    fireEvent.click(retryButton);

    await waitFor(() => expect(screen.getByText("Riley Fox")).not.toBeNull());
    expect(fetchProgramTeam).toHaveBeenLastCalledWith("PROG-100", "30d");
  });

  it("the range switcher is keyboard-operable: real buttons with aria-pressed reflecting the active range", async () => {
    fetchProgramTeam.mockResolvedValue(okResult([member()]));

    render(<ProgramTeamPanel programId="PROG-100" />);

    await waitFor(() =>
      expect(fetchProgramTeam).toHaveBeenCalledWith("PROG-100", "30d"),
    );

    const group = screen.getByRole("group", {
      name: "Select date range for project team",
    });
    const btn7d = within(group).getByRole("button", { name: "7D" });
    const btn30d = within(group).getByRole("button", { name: "30D" });
    const btn90d = within(group).getByRole("button", { name: "90D" });

    expect(btn30d.getAttribute("aria-pressed")).toBe("true");
    expect(btn7d.getAttribute("aria-pressed")).toBe("false");
    expect(btn90d.getAttribute("aria-pressed")).toBe("false");

    fetchProgramTeam.mockResolvedValue(okResult([member()]));
    fireEvent.click(btn7d);

    await waitFor(() => expect(btn7d.getAttribute("aria-pressed")).toBe("true"));
    expect(btn30d.getAttribute("aria-pressed")).toBe("false");
  });

  it("column head row exposes screen-reader-navigable header cells (NFR-008)", async () => {
    fetchProgramTeam.mockResolvedValue(okResult([member()]));

    render(<ProgramTeamPanel programId="PROG-100" />);

    await waitFor(() => expect(screen.getByText("Riley Fox")).not.toBeNull());

    expect(screen.getAllByRole("columnheader")).toHaveLength(5);
    expect(screen.getByRole("columnheader", { name: "Member" })).not.toBeNull();
    expect(screen.getByRole("columnheader", { name: "Avg / session" })).not.toBeNull();
  });

  it("renders each row as a native button with an explicit accessible name and aria-haspopup (T-16, DESIGN.md § 2.1)", async () => {
    fetchProgramTeam.mockResolvedValue(okResult([member()]));

    render(<ProgramTeamPanel programId="PROG-100" />);

    const rowButton = await screen.findByRole("button", {
      name: "View usage for Riley Fox, Developer",
    });
    expect(rowButton.tagName).toBe("BUTTON");
    expect(rowButton.getAttribute("aria-haspopup")).toBe("dialog");
    // No dialog is open until the row is activated.
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("activating a row opens the member usage popup scoped to that member", async () => {
    fetchProgramTeam.mockResolvedValue(
      okResult([member({ member_id: "user-devon-rao", member_name: "Devon Rao" })]),
    );
    fetchMemberUsage.mockReturnValue(new Promise(() => {})); // never resolves -- loading only

    render(<ProgramTeamPanel programId="PROG-100" />);

    const rowButton = await screen.findByRole("button", {
      name: "View usage for Devon Rao, Developer",
    });
    fireEvent.click(rowButton);

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Devon Rao")).not.toBeNull();
    // D-06: the popup is addressed by member_id (a stable roster identity id), not the
    // display-only member_name -- this is the regression Q-01 describes.
    expect(fetchMemberUsage).toHaveBeenCalledWith("PROG-100", "user-devon-rao", "30d");
  });

  it("closing the popup restores focus to the row button that opened it", async () => {
    fetchProgramTeam.mockResolvedValue(okResult([member({ member_name: "Devon Rao" })]));
    fetchMemberUsage.mockReturnValue(new Promise(() => {}));

    render(<ProgramTeamPanel programId="PROG-100" />);

    const rowButton = await screen.findByRole("button", {
      name: "View usage for Devon Rao, Developer",
    });
    fireEvent.click(rowButton);

    const dialog = await screen.findByRole("dialog");
    const closeButton = within(dialog).getByRole("button", {
      name: "Close usage for Devon Rao",
    });
    fireEvent.click(closeButton);

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(rowButton));
  });

  it("an unresolved member_name degrades the row's accessible name to a neutral fallback (DESIGN.md § Sample names never shipped)", async () => {
    fetchProgramTeam.mockResolvedValue(okResult([member({ member_name: "" })]));

    render(<ProgramTeamPanel programId="PROG-100" />);

    const rowButton = await screen.findByRole("button", {
      name: "View usage for this member",
    });
    expect(rowButton).not.toBeNull();
  });
});
