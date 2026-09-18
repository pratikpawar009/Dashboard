import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { AdoptionOverview } from "./AdoptionOverview";
import { ProgramLeaderboard } from "./ProgramLeaderboard";
import type { OverviewSummaryResult } from "@/types/overview";
import type { ProgramBoardCardData } from "@/types/programBoard";

/**
 * OVW-04-TC-08 (frontend half) -- empty-state rendering with no invented
 * copy, and the exactly-6-skeleton loading state (PO resolution #4: assert 6,
 * never `page_size`).
 *
 * Same idiom as `OrgSummaryCards.test.tsx` / `AdoptionOverview.test.tsx`: no
 * `jest-dom` matchers, explicit `cleanup()` in `afterEach`.
 */

afterEach(() => {
  cleanup();
});

const ITEMS: ProgramBoardCardData[] = [
  {
    program_id: "program-b",
    name: "Bravo",
    type: "Migration",
    icon: "BR",
    description: "Bravo description",
    href: "/programs/program-b",
    sparkline: { points: [], mom_change_percent: null, mom_direction: null },
    metrics: [
      { glyph: "⬡", label: "Total tokens", value: "2.0M" },
      { glyph: "⤴", label: "Releases", value: "10" },
      { glyph: "</>", label: "Features", value: "20" },
      { glyph: "◎", label: "Active contributors", value: "12" },
    ],
    repos_with_harness_installed: 6,
    repos_total: 6,
  },
  {
    program_id: "program-c",
    name: "Charlie",
    type: "Greenfield feature development",
    icon: "CH",
    description: "Charlie description",
    href: "/programs/program-c",
    sparkline: { points: [], mom_change_percent: null, mom_direction: null },
    metrics: [
      { glyph: "⬡", label: "Total tokens", value: "1.2M" },
      { glyph: "⤴", label: "Releases", value: "7" },
      { glyph: "</>", label: "Features", value: "9" },
      { glyph: "◎", label: "Active contributors", value: "8" },
    ],
    repos_with_harness_installed: 4,
    repos_total: 5,
  },
];

describe("ProgramLeaderboard — loading state (PO resolution #4)", () => {
  it("renders exactly 6 skeleton placeholders regardless of page_size", () => {
    render(<ProgramLeaderboard state="loading" />);

    const placeholders = screen.getAllByTestId(
      "program-leaderboard-card-placeholder",
    );
    expect(placeholders).toHaveLength(6);
  });

  it("renders no populated cards and no card text while loading", () => {
    render(<ProgramLeaderboard state="loading" />);

    expect(screen.queryAllByRole("link")).toHaveLength(0);
    screen.getAllByTestId("program-leaderboard-card-placeholder").forEach((el) => {
      expect(el.textContent).toBe("");
    });
  });

  it("still renders the section heading while loading", () => {
    render(<ProgramLeaderboard state="loading" />);

    expect(screen.getByText("Program board").textContent).toBe("Program board");
  });
});

describe("ProgramLeaderboard — populated state", () => {
  it("renders one ProgramCard per item in the exact backend order (tokens DESC, never re-sorted)", () => {
    const { container } = render(
      <ProgramLeaderboard state="populated" items={ITEMS} />,
    );

    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(2);
    expect(links[0].getAttribute("href")).toBe("/programs/program-b");
    expect(links[1].getAttribute("href")).toBe("/programs/program-c");
  });

  it("renders the section heading and suffix", () => {
    render(<ProgramLeaderboard state="populated" items={ITEMS} />);

    expect(screen.getByText("Program board").textContent).toBe("Program board");
    expect(screen.getByText("— all programs using Harness").textContent).toBe(
      "— all programs using Harness",
    );
  });
});

describe("ProgramLeaderboard — empty state (OVW-04-TC-08 frontend half, AC-5)", () => {
  it("renders the section header with an empty card stack, no cards, no placeholders", () => {
    render(<ProgramLeaderboard state="populated" items={[]} />);

    expect(screen.getByText("Program board").textContent).toBe("Program board");
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(
      screen.queryAllByTestId("program-leaderboard-card-placeholder"),
    ).toHaveLength(0);
  });

  it("invents no empty-state copy -- the mockup has none for this section", () => {
    render(<ProgramLeaderboard state="populated" items={[]} />);

    expect(screen.queryByText(/no programs/i)).toBeNull();
    expect(screen.queryByText(/nothing to show/i)).toBeNull();
    expect(screen.queryByText(/get started/i)).toBeNull();
    expect(screen.queryByText(/no data/i)).toBeNull();
  });

  it("also renders an empty stack when items is omitted entirely (defaults to [])", () => {
    render(<ProgramLeaderboard state="populated" />);

    expect(screen.getByText("Program board").textContent).toBe("Program board");
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });
});

describe("regression-OVW-01-TC-06/07 — AdoptionOverview omitted programBoardResult", () => {
  const RESULT: OverviewSummaryResult = {
    status: "ok",
    data: {
      cards: [
        { glyph: "▦", value: "7 / 10", label: "Programs using AI SDLC", sub: "70% adoption" },
      ],
      programs_using_ai: { count: 7, total: 10, adoption_percent: 70.0 },
    },
  };

  // Root cause (fixed here): AdoptionOverview previously defaulted the
  // omitted `programBoardResult` prop to `{status: "error"}`, conflating
  // "caller did not pass a board" with "the board fetch failed" and
  // rendering `OverviewErrorPanel` for callers that predate OVW-04 (this
  // repro is exactly OVW-01's own pre-existing call shape). An omitted prop
  // must render neither the leaderboard region nor an error panel.
  it("renders no Program board heading and no error panel when programBoardResult is omitted", () => {
    render(<AdoptionOverview result={RESULT} />);

    expect(screen.queryByText("Program board")).toBeNull();
    expect(screen.queryByText("You don't have access to this view.")).toBeNull();
  });
});
