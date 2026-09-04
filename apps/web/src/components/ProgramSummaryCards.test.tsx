import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ProgramSummaryCards } from "./ProgramSummaryCards";
import type { ProgramSummaryCardData } from "@/types/programDetail";

afterEach(() => {
  cleanup();
});

// Mockup order (DESIGN.md Region 4) — order is part of the contract
// (D-06/ADR-0007), asserted explicitly below, not merely rendered.
const SAMPLE_CARDS: ProgramSummaryCardData[] = [
  { glyph: "⬡", value: "128.4K", label: "Token consumption" },
  { glyph: "✦", value: "42", label: "Features delivered via Harness" },
  { glyph: "⤴", value: "17", label: "Releases done via Harness" },
  { glyph: "❯", value: "9 / 12", label: "Repos with Harness installed" },
  { glyph: "›_", value: "3.2K", label: "Commands executed" },
  { glyph: "</>", value: "58.1K", label: "Lines of code generated" },
  { glyph: "≡", value: "64", label: "User stories delivered" },
];

describe("ProgramSummaryCards (PGD-01-AC-3)", () => {
  it("renders the 7 cards in the exact backend order, glyph/value/label verbatim", () => {
    render(<ProgramSummaryCards state="populated" cards={SAMPLE_CARDS} />);

    const cards = screen.getAllByTestId("program-summary-card");
    expect(cards).toHaveLength(7);

    // Order assertion: each card's rendered text, read in DOM order, must
    // match the input array's order exactly -- the component must not
    // re-sort or re-index the `summary` array (D-06/ADR-0007).
    expect(cards.map((card) => card.textContent)).toEqual(
      SAMPLE_CARDS.map((card) => `${card.glyph}${card.value}${card.label}`),
    );
  });

  it("renders 7 loading placeholders with no card text and no populated cards", () => {
    render(<ProgramSummaryCards state="loading" />);

    const placeholders = screen.getAllByTestId(
      "program-summary-card-placeholder",
    );
    expect(placeholders).toHaveLength(7);
    placeholders.forEach((placeholder) => {
      expect(placeholder.textContent).toBe("");
    });
    expect(screen.queryByTestId("program-summary-card")).toBeNull();
  });
});
