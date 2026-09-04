import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { BackToProgramBoard } from "./BackToProgramBoard";
import { ADOPTION_OVERVIEW_ROUTE } from "@/lib/routes";

afterEach(() => {
  cleanup();
});

describe("BackToProgramBoard (PGD-01-AC-4)", () => {
  it("renders a link targeting the imported ADOPTION_OVERVIEW_ROUTE constant", () => {
    render(<BackToProgramBoard />);

    const link = screen.getByRole("link", {
      name: "← Back to program board",
    });

    // Asserted against the imported constant, not a hardcoded "/overview"
    // literal, so this test stays correct when OVW-01 changes the value.
    expect(link.getAttribute("href")).toBe(ADOPTION_OVERVIEW_ROUTE);
  });

  it("is keyboard-reachable and exposes an accessible name", () => {
    render(<BackToProgramBoard />);

    const link = screen.getByRole("link", {
      name: "← Back to program board",
    });

    link.focus();
    expect(document.activeElement).toBe(link);
  });
});
