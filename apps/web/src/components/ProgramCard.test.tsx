import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ProgramCard } from "./ProgramCard";
import type { ProgramBoardCardData } from "@/types/programBoard";

/**
 * OVW-04-TC-06 / TC-07 / TC-12 — the single program board card.
 *
 * Assertions use plain vitest matchers (`toBeNull`, `toBe`, `toHaveLength`,
 * `.textContent`) -- this project deliberately wires up **no** `jest-dom`
 * matchers (see `AdoptionOverview.test.tsx`). Do not reach for
 * `toBeInTheDocument`.
 *
 * `vitest.config.ts` declares no `setupFiles`, so Testing Library's
 * auto-cleanup is NOT wired -- every test file unmounts explicitly in
 * `afterEach`.
 */

afterEach(() => {
  cleanup();
});

// Deliberately distinctive/unusual values (TC-07) -- nothing here matches any
// plausible hardcoded placeholder, so a literal in the component source would
// fail these assertions rather than accidentally pass them.
const CARD: ProgramBoardCardData = {
  program_id: "prog-zzz",
  name: "Zzz-Test-Program",
  type: "Brownfield migration",
  icon: "ZQ",
  description: "Distinctive test description XQ42",
  href: "/programs/prog-zzz",
  sparkline: {
    points: [
      { month: "2026-07", tokens: 1000 },
      { month: "2026-08", tokens: 1200 },
    ],
    mom_change_percent: 12.5,
    mom_direction: "up",
  },
  metrics: [
    { glyph: "⬡", label: "Total tokens", value: "999.9K" },
    { glyph: "⤴", label: "Releases", value: "13" },
    { glyph: "</>", label: "Features", value: "27" },
    { glyph: "◎", label: "Active contributors", value: "9" },
  ],
  repos_with_harness_installed: 1,
  repos_total: 7,
};

describe("ProgramCard — navigation (OVW-04-TC-06)", () => {
  it("renders a single <a> root whose href equals card.href verbatim", () => {
    const { container } = render(<ProgramCard card={CARD} />);

    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe("/programs/prog-zzz");
  });

  it("never reconstructs href from program_id -- consumes the wire value as-is", () => {
    // A different href than `/programs/{program_id}` would convention-imply,
    // proving the component doesn't derive it client-side.
    const oddCard: ProgramBoardCardData = {
      ...CARD,
      program_id: "prog-zzz",
      href: "/programs/some-other-slug",
    };
    const { container } = render(<ProgramCard card={oddCard} />);

    expect(container.querySelector("a")?.getAttribute("href")).toBe(
      "/programs/some-other-slug",
    );
  });

  it("logs program_drilldown on click without preventing navigation (D-06)", () => {
    const { container } = render(<ProgramCard card={CARD} />);
    const link = container.querySelector("a") as HTMLAnchorElement;

    const logged: string[] = [];
    const originalInfo = console.info;
    console.info = (msg: string) => {
      logged.push(msg);
    };
    try {
      const event = fireEvent.click(link);
      // fireEvent.click returns false only if preventDefault() was called.
      expect(event).toBe(true);
    } finally {
      console.info = originalInfo;
    }

    expect(logged.length).toBe(1);
    const parsed = JSON.parse(logged[0]);
    expect(parsed.event).toBe("program_drilldown");
    expect(parsed.program_id).toBe("prog-zzz");
  });

  it("is keyboard reachable — the root is a real <a> with a real href, not a div with a click handler", () => {
    const { container } = render(<ProgramCard card={CARD} />);
    const link = container.querySelector("a");

    expect(link).not.toBeNull();
    expect(link?.tagName).toBe("A");
    expect(link?.getAttribute("href")).toBeTruthy();
    expect(link?.getAttribute("aria-label")).toBe(
      "Zzz-Test-Program — open program detail",
    );
  });
});

describe("ProgramCard — no hardcoded or illustrative values (OVW-04-TC-07 / AC-4 / R-08)", () => {
  it("renders name, type, description exactly as supplied", () => {
    render(<ProgramCard card={CARD} />);

    expect(screen.getByText("Zzz-Test-Program").textContent).toBe(
      "Zzz-Test-Program",
    );
    expect(screen.getByText("Brownfield migration").textContent).toBe(
      "Brownfield migration",
    );
    expect(
      screen.getByText("Distinctive test description XQ42").textContent,
    ).toBe("Distinctive test description XQ42");
  });

  it("renders all 4 metrics in server-given order with glyph/label/value verbatim", () => {
    const { container } = render(<ProgramCard card={CARD} />);

    const boxes = container.querySelectorAll(
      `[class*="metricBox"]`,
    ) as NodeListOf<HTMLElement>;
    expect(boxes).toHaveLength(4);
    CARD.metrics.forEach((metric, i) => {
      const text = boxes[i].textContent ?? "";
      expect(text).toContain(metric.glyph);
      expect(text).toContain(metric.label);
      expect(text).toContain(metric.value);
    });
  });

  it("renders the repo ratio '1 / 7' composed from the raw ints, not a server string", () => {
    render(<ProgramCard card={CARD} />);

    expect(screen.getByText("1 / 7").textContent).toBe("1 / 7");
  });

  it("guards a 0/0 repo ratio with no NaN in the fill width", () => {
    const zeroCard: ProgramBoardCardData = {
      ...CARD,
      repos_with_harness_installed: 0,
      repos_total: 0,
    };
    const { container } = render(<ProgramCard card={zeroCard} />);

    expect(screen.getByText("0 / 0").textContent).toBe("0 / 0");
    const fill = container.querySelector(`[class*="fill"]`) as HTMLElement;
    expect(fill.style.width).toBe("0%");
  });

  it("renders every figure traceable to the fixture -- no illustrative sample string appears", () => {
    const { container } = render(<ProgramCard card={CARD} />);

    // Known mockup-sample strings that must never leak into rendered output
    // regardless of what fixture is passed in.
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/lorem ipsum/i);
    expect(text).not.toContain("Acme");
    expect(text).not.toContain("Sample Program");
  });
});

describe("ProgramCard — MoM change indicator, non-color-reliant (OVW-04-TC-12)", () => {
  it("pairs the 'up' direction with a glyph/label, not color alone", () => {
    render(<ProgramCard card={CARD} />);

    // momGlyphLabel renders "▲ 12.5%" -- direction is carried by the glyph
    // and the numeric label text, not merely a style attribute.
    const chip = screen.getByLabelText("up 12.5 percent");
    expect(chip.textContent).toContain("▲");
    expect(chip.textContent).toContain("12.5%");
  });

  it("pairs the 'down' direction with a distinct glyph/label", () => {
    const downCard: ProgramBoardCardData = {
      ...CARD,
      sparkline: { ...CARD.sparkline, mom_change_percent: -8.2, mom_direction: "down" },
    };
    render(<ProgramCard card={downCard} />);

    const chip = screen.getByLabelText("down 8.2 percent");
    expect(chip.textContent).toContain("▼");
    expect(chip.textContent).toContain("8.2%");
  });

  it("renders the flat direction with its own glyph/label, distinct from up/down", () => {
    const flatCard: ProgramBoardCardData = {
      ...CARD,
      sparkline: { ...CARD.sparkline, mom_change_percent: 0, mom_direction: "flat" },
    };
    render(<ProgramCard card={flatCard} />);

    const chip = screen.getByLabelText("flat 0 percent");
    expect(chip.textContent).toContain("—");
    expect(chip.textContent).not.toContain("▲");
    expect(chip.textContent).not.toContain("▼");
  });

  it("omits the chip entirely for the neutral (null/null) state -- no arrow, no color", () => {
    const neutralCard: ProgramBoardCardData = {
      ...CARD,
      sparkline: { points: [], mom_change_percent: null, mom_direction: null },
    };
    const { container } = render(<ProgramCard card={neutralCard} />);

    expect(container.querySelector(`[class*="momChip"]`)).toBeNull();
    expect(screen.queryByLabelText(/percent/)).toBeNull();
  });
});
