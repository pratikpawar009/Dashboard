import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { AdoptionIndicator } from "./AdoptionIndicator";
import type { ProgramsUsingAiData } from "@/types/overview";

afterEach(() => {
  cleanup();
});

const POPULATED_DATA: ProgramsUsingAiData = {
  count: 7,
  total: 10,
  adoption_percent: 70.0,
};

// FR-4 zero state: `adoption_percent` is `null`, never `0`, when
// `programs_total === 0` -- the component must render off of `null`, not a
// coalesced `0`.
const ZERO_STATE_DATA: ProgramsUsingAiData = {
  count: 0,
  total: 0,
  adoption_percent: null,
};

describe("AdoptionIndicator (OVW-01-AC-4)", () => {
  it("renders the rendered heading text 'Adoption Level', not the mockup's 'PROGRAM ADOPTION HEALTH' section comment", () => {
    render(<AdoptionIndicator state="populated" data={POPULATED_DATA} />);

    expect(screen.getByText("Adoption Level")).not.toBeNull();
    expect(screen.queryByText(/PROGRAM ADOPTION HEALTH/i)).toBeNull();
  });

  it("populated: headline '<count> / <total>' (spaced, D-05), subtitle with rounded percent, 2-segment bar and 2-entry legend with client-derived colors", () => {
    render(<AdoptionIndicator state="populated" data={POPULATED_DATA} />);

    expect(screen.getByTestId("adoption-headline").textContent).toBe(
      "7 / 10",
    );
    expect(screen.getByTestId("adoption-subtitle").textContent).toBe(
      "programs using AI SDLC · 70% of the org",
    );

    const segments = screen.getAllByTestId("adoption-bar-segment");
    expect(segments).toHaveLength(2);
    expect(segments[0].style.width).toBe("70%");
    expect(segments[0].style.backgroundColor).toBe("rgb(42, 111, 219)"); // #2a6fdb
    expect(segments[1].style.width).toBe("30%");
    expect(segments[1].style.backgroundColor).toBe("rgb(223, 227, 233)"); // #dfe3e9

    const entries = screen.getAllByTestId("adoption-legend-entry");
    expect(entries).toHaveLength(2);
    expect(entries[0].textContent).toBe("7Using AI SDLC");
    expect(entries[1].textContent).toBe("3Not yet adopted");

    // Color is never the sole indicator (NFR-008) -- each legend entry
    // pairs its swatch with visible count + label text, asserted above.
  });

  it("zero state (programs_total === 0, adoption_percent === null, FR-4/TC-07): literal '0/0' headline, no percent clause, 1 flat bar segment, both legend counts 0", () => {
    render(<AdoptionIndicator state="populated" data={ZERO_STATE_DATA} />);

    expect(screen.getByTestId("adoption-headline").textContent).toBe("0/0");
    expect(screen.getByTestId("adoption-subtitle").textContent).toBe(
      "programs using AI SDLC",
    );

    const segments = screen.getAllByTestId("adoption-bar-segment");
    expect(segments).toHaveLength(1);
    expect(segments[0].style.width).toBe("100%");
    expect(segments[0].style.backgroundColor).toBe("rgb(223, 227, 233)"); // #dfe3e9, not the brand blue

    const entries = screen.getAllByTestId("adoption-legend-entry");
    expect(entries).toHaveLength(2);
    expect(entries[0].textContent).toBe("0Using AI SDLC");
    expect(entries[1].textContent).toBe("0Not yet adopted");
  });

  it("renders 2-entry loading skeleton with no headline/subtitle/legend text", () => {
    render(<AdoptionIndicator state="loading" />);

    expect(screen.queryByTestId("adoption-headline")).toBeNull();
    expect(screen.queryByTestId("adoption-subtitle")).toBeNull();
    expect(screen.getByTestId("adoption-bar-placeholder")).not.toBeNull();
    expect(screen.getAllByTestId("adoption-legend-placeholder")).toHaveLength(
      2,
    );
    expect(screen.queryByTestId("adoption-legend-entry")).toBeNull();
  });
});
